################################################################################
# File Name: backfill_ecu_lineage.py
# Purpose/Description: F-108 (US-367) one-shot ECU-lineage bootstrap/backfill
#                      CLI.  Establishes the historical vehicle_info ECU spine as
#                      exactly TWO real ECU-era rows -- prior ECU (active before
#                      the ~2026-05-22 swap) + new modified-EPROM ECU (active from
#                      the swap onward) -- SUPERSEDING the degenerate
#                      PRE_TRACKING_UNKNOWN bootstrap placeholder (a failed
#                      bootstrap, NOT lineage; Atlas 2026-06-28 2-row ruling).
#                      Per Atlas, stamp_ecu_swap CANNOT bootstrap the first row
#                      (it has nothing to close -- getActiveVehicleInfo() is None
#                      once the placeholder is closed); this script is the SOLE
#                      sanctioned exception to "stamp_ecu_swap is the only
#                      vehicle_info mutator," scoped to initial spine
#                      establishment.  Both eras resolve their ecu_id via
#                      resolveOrCreateEcu and DERIVE the transitional TEXT
#                      ecu_signature/cal_signature snapshot columns from the
#                      resolved ecu row (so vehicle_info <-> ecu stays coherent).
#
#                      Install/removal boundaries form a gapless single-active
#                      partition so any drive's start_time resolves to exactly one
#                      ECU era (and the stuck dtc_freeze_frame sync orphan
#                      self-heals).  The swap instant + start-of-tracking instant
#                      are SCRIPT PARAMS (Spool-derived), never hardcoded.
#
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-29
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-29    | Rex (US-367) | Initial -- one-shot ECU-lineage backfill CLI.
# ================================================================================
################################################################################

"""F-108 one-shot ECU-lineage bootstrap/backfill CLI (US-367).

Supersede the degenerate ``PRE_TRACKING_UNKNOWN`` placeholder and write the two
real ECU eras as a gapless single-active partition.

Usage::

    python -m server.cli.backfill_ecu_lineage \\
        --prior-signature MD346675 --prior-cal-signature 6675 \\
        --new-signature   MD326328 --new-cal-signature   UNKCAL \\
        --start-of-tracking 2026-04-23T16:36:50Z \\
        --swap-instant      2026-05-22T18:35:26Z

``--vin`` / ``--source-device`` are inherited from the superseded placeholder
when present; pass them explicitly only when bootstrapping a DB with no
placeholder to inherit from.

On the "NULL" prior-ECU install (Atlas vs. the shipped resolver)
---------------------------------------------------------------
Atlas's 2026-06-28 ruling describes the prior-ECU install as the "gapless
partition start (NULL)".  The shipped schema declares
``vehicle_info.ecu_install_timestamp_utc`` ``NOT NULL`` and the resolver
(``src.server.api.sync._resolveVehicleInfoIdForCapture``) matches an era with
``ecu_install_timestamp_utc <= captured_at`` -- so a literal SQL ``NULL`` install
is BOTH unstorable AND unmatchable (it would make the prior era resolve zero
captures, breaking the drives 1-24 partition this backfill exists to repair).
The conceptual "unbounded lower bound" is therefore realized as the grounded
START-OF-TRACKING instant (earliest ``realtime_data.timestamp`` =
``2026-04-23 16:36:50 UTC``, per US-367 grounded facts / Atlas Refinements row 9),
which sits at-or-before every tracked capture and so is operationally identical
to an unbounded start over all real data.  This is a documented reconciliation
of the ruling's wording with the shipped code, not a silent deviation.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.cli._ecu_lineage_support import (
    PRE_MIGRATION_MESSAGE,
    ecuLineageColumnsPresent,
    nextSourceId,
    parseIsoTimestamp,
    resolveOrCreateEcu,
    resolveSyncDatabaseUrl,
)
from src.server.db.models import (
    VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN,
    DriveSummary,
    VehicleInfo,
)

logger = logging.getLogger(__name__)

# Exit codes (see Quality + Safety Constants): 0 success / 1 config / 2 runtime.
EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_RUNTIME = 2


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.cli.backfill_ecu_lineage",
        description=(
            "One-shot ECU-lineage bootstrap: supersede the PRE_TRACKING_UNKNOWN "
            "placeholder + write the two real ECU eras (prior closed at the swap "
            "instant, new currently-active)."
        ),
    )
    parser.add_argument(
        "--prior-signature", required=True, metavar="ID",
        help="ECU signature of the PRIOR ECU (active before the swap).",
    )
    parser.add_argument(
        "--prior-cal-signature", default=None, metavar="ID",
        help="Calibration signature of the prior ECU (optional -> UNKCAL).",
    )
    parser.add_argument(
        "--new-signature", required=True, metavar="ID",
        help="ECU signature of the NEW ECU (currently active).",
    )
    parser.add_argument(
        "--new-cal-signature", default=None, metavar="ID",
        help="Calibration signature of the new ECU (optional -> UNKCAL).",
    )
    parser.add_argument(
        "--start-of-tracking", required=True, metavar="ISO8601",
        help=(
            "Prior-ECU install instant = start-of-tracking (earliest tracked "
            "capture).  The concrete realization of the 'NULL' gapless partition "
            "start (the column is NOT NULL; the resolver compares install <= "
            "captured_at).  Source: earliest realtime_data.timestamp."
        ),
    )
    parser.add_argument(
        "--swap-instant", required=True, metavar="ISO8601",
        help=(
            "Swap instant (prior removal == new install).  Spool-derived from "
            "the last old-ECU / first new-ECU sample; passed as a PARAM, never "
            "hardcoded."
        ),
    )
    parser.add_argument(
        "--vin", default=None, metavar="VIN",
        help=(
            "Vehicle VIN for the two era rows.  Inherited from the superseded "
            "placeholder when present; required only on a placeholder-less DB."
        ),
    )
    parser.add_argument(
        "--source-device", default=None, metavar="DEVICE",
        help=(
            "source_device namespace for the two era rows.  Inherited from the "
            "placeholder when present; required only on a placeholder-less DB."
        ),
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m server.cli.backfill_ecu_lineage``."""
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    try:
        startOfTracking = parseIsoTimestamp(args.start_of_tracking)
        swapInstant = parseIsoTimestamp(args.swap_instant)
    except ValueError as exc:
        logger.error(
            "backfill_ecu_lineage | ERROR | invalid ISO-8601 timestamp (%s)",
            exc,
        )
        return EXIT_RUNTIME

    if startOfTracking >= swapInstant:
        logger.error(
            "backfill_ecu_lineage | ERROR | start-of-tracking %s must be before "
            "the swap instant %s (prior era would be empty/inverted).",
            startOfTracking, swapInstant,
        )
        return EXIT_RUNTIME

    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    try:
        if not ecuLineageColumnsPresent(engine):
            logger.error("backfill_ecu_lineage | ERROR | %s", PRE_MIGRATION_MESSAGE)
            return EXIT_CONFIG

        with Session(engine) as session:
            return _backfill(
                session,
                priorSignature=args.prior_signature,
                priorCalSignature=args.prior_cal_signature,
                newSignature=args.new_signature,
                newCalSignature=args.new_cal_signature,
                startOfTracking=startOfTracking,
                swapInstant=swapInstant,
                vin=args.vin,
                sourceDevice=args.source_device,
            )
    finally:
        engine.dispose()


def _isExpectedTwoEra(
    realRows: list[VehicleInfo], priorSignature: str, newSignature: str,
) -> bool:
    """True when the table already holds exactly the two expected ECU eras.

    Lets a re-run detect the already-backfilled state and no-op idempotently:
    exactly two non-placeholder rows whose signatures are the prior + new ECUs,
    with the new ECU the single currently-active (removal NULL) row.
    """
    if len(realRows) != 2:
        return False
    signatures = {r.ecu_signature for r in realRows}
    if signatures != {priorSignature, newSignature}:
        return False
    active = [r for r in realRows if r.ecu_removal_timestamp_utc is None]
    return len(active) == 1 and active[0].ecu_signature == newSignature


def _backfill(
    session: Session,
    *,
    priorSignature: str,
    priorCalSignature: str | None,
    newSignature: str,
    newCalSignature: str | None,
    startOfTracking: datetime,
    swapInstant: datetime,
    vin: str | None,
    sourceDevice: str | None,
) -> int:
    """Supersede the placeholder + write the two real ECU eras (one transaction).

    Returns an exit code; commits only the clean-write path.  Idempotent re-run
    is a no-op; pre-existing REAL lineage is refused (this is a one-shot
    bootstrap, never a lineage overwrite).
    """
    existing = session.execute(select(VehicleInfo)).scalars().all()
    placeholders = [
        r for r in existing
        if r.ecu_signature == VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN
    ]
    realRows = [
        r for r in existing
        if r.ecu_signature != VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN
    ]

    # Idempotent re-run: the two expected eras already exist (placeholder gone).
    if not placeholders and _isExpectedTwoEra(
        realRows, priorSignature, newSignature,
    ):
        logger.info(
            "backfill_ecu_lineage | no-op | the two ECU eras (%s, %s) are "
            "already present; nothing to bootstrap.",
            priorSignature, newSignature,
        )
        return EXIT_OK

    # Safety: refuse to overwrite real (non-placeholder) lineage.  This script
    # only ESTABLISHES the spine over a placeholder; steady-state swaps are
    # stamp_ecu_swap's job.
    if realRows:
        logger.error(
            "backfill_ecu_lineage | REFUSED | %d real (non-placeholder) "
            "vehicle_info row(s) already exist; the one-shot bootstrap will not "
            "overwrite established lineage.  Use stamp_ecu_swap for swaps.",
            len(realRows),
        )
        return EXIT_RUNTIME

    resolvedVin = vin if vin is not None else (
        placeholders[0].vin if placeholders else None
    )
    resolvedDevice = sourceDevice if sourceDevice is not None else (
        placeholders[0].source_device if placeholders else None
    )
    if resolvedVin is None or resolvedDevice is None:
        logger.error(
            "backfill_ecu_lineage | ERROR | no placeholder to inherit from and "
            "--vin / --source-device not supplied; cannot author the era rows.",
        )
        return EXIT_CONFIG

    # Provenance: record the superseded placeholder(s) in the log (NOT retained
    # as a live lineage row -- Atlas: a failed bootstrap is not lineage).
    for placeholder in placeholders:
        logger.info(
            "backfill_ecu_lineage | superseding placeholder | id=%s "
            "ecu_signature=%s install=%s removal=%s (zero-width bootstrap "
            "stub; deleted, not retained)",
            placeholder.id, placeholder.ecu_signature,
            placeholder.ecu_install_timestamp_utc,
            placeholder.ecu_removal_timestamp_utc,
        )
        session.delete(placeholder)
    session.flush()

    # Prior ECU era: [start-of-tracking, swap).  Closed (removal set) -> marker
    # NULL, so it never collides on the single-active unique index.
    priorEcu = resolveOrCreateEcu(
        session, signature=priorSignature, calSignature=priorCalSignature,
    )
    session.add(
        VehicleInfo(
            source_id=nextSourceId(session, resolvedDevice),
            source_device=resolvedDevice,
            vin=resolvedVin,
            ecu_id=priorEcu.id,
            ecu_signature=priorEcu.ecu_signature,
            cal_signature=priorEcu.cal_signature,
            ecu_install_timestamp_utc=startOfTracking,
            ecu_removal_timestamp_utc=swapInstant,
            notes=(
                "US-367 bootstrap backfill: prior ECU era; install = "
                "start-of-tracking (earliest realtime_data.timestamp), the "
                "concrete realization of the gapless partition start."
            ),
        )
    )
    session.flush()

    # New ECU era: [swap, NULL).  Currently active -> marker 1 (the sole active).
    newEcu = resolveOrCreateEcu(
        session, signature=newSignature, calSignature=newCalSignature,
    )
    session.add(
        VehicleInfo(
            source_id=nextSourceId(session, resolvedDevice),
            source_device=resolvedDevice,
            vin=resolvedVin,
            ecu_id=newEcu.id,
            ecu_signature=newEcu.ecu_signature,
            cal_signature=newEcu.cal_signature,
            ecu_install_timestamp_utc=swapInstant,
            ecu_removal_timestamp_utc=None,
            notes="US-367 bootstrap backfill: new modified-EPROM ECU era (active).",
        )
    )
    session.flush()

    # Self-check the partition BEFORE committing.  Overlap (a drive matching >1
    # era) is the resolver hazard Atlas warned about -- fatal, roll back.
    report = verifyDrivePartition(session)
    if report["overlapping"]:
        logger.error(
            "backfill_ecu_lineage | ERROR | %d drive(s) match BOTH ECU eras "
            "(overlapping windows): %s.  Rolling back -- fix the boundaries.",
            len(report["overlapping"]), report["overlapping"],
        )
        session.rollback()
        return EXIT_RUNTIME
    if report["unresolved"]:
        # Non-fatal: a drive before start-of-tracking is an edge worth surfacing
        # but does not invalidate the two-era spine.
        logger.warning(
            "backfill_ecu_lineage | WARNING | %d drive(s) resolve to NO ECU era "
            "(start_time before start-of-tracking): %s.",
            len(report["unresolved"]), report["unresolved"],
        )

    session.commit()
    logger.info(
        "backfill_ecu_lineage | OK | superseded %d placeholder(s); wrote prior "
        "era %s [%s -> %s] + active era %s [%s -> open].  Partition: %d prior / "
        "%d new drive(s).",
        len(placeholders), priorSignature, startOfTracking, swapInstant,
        newSignature, swapInstant,
        report["priorDriveCount"], report["newDriveCount"],
    )
    return EXIT_OK


def verifyDrivePartition(session: Session) -> dict:
    """Partition drive_summary rows across the ECU eras by their start_time window.

    Mirrors the production resolver's window logic
    (``install <= start_time AND (removal IS NULL OR removal >= start_time)``)
    over the single-vehicle ``drive_summary`` table, so the backfill (and an
    operator at deploy) can confirm V-6/V-7: every drive resolves to exactly one
    era, drives before the swap to the prior ECU and drives at/after to the new
    ECU, with no overlapping (``>1``) or unresolved (``0``) windows.

    Args:
        session: An open SQLAlchemy session bound to the server schema.

    Returns:
        A report dict: ``priorSignature`` / ``newSignature`` (derived: the active
        era is "new", the closed era "prior"), ``priorDriveCount`` /
        ``newDriveCount``, and ``unresolved`` / ``overlapping`` lists of
        ``source_id`` for drives matching 0 or >1 era.
    """
    eras = session.execute(select(VehicleInfo)).scalars().all()
    active = [e for e in eras if e.ecu_removal_timestamp_utc is None]
    closed = [e for e in eras if e.ecu_removal_timestamp_utc is not None]
    newSignature = active[0].ecu_signature if active else None
    # The most recently-closed non-placeholder era is the "prior" ECU.
    priorEra = max(
        (e for e in closed
         if e.ecu_signature != VEHICLE_INFO_ECU_SIGNATURE_UNKNOWN),
        key=lambda e: e.ecu_install_timestamp_utc,
        default=None,
    )
    priorSignature = priorEra.ecu_signature if priorEra is not None else None

    drives = session.execute(
        select(DriveSummary.source_id, DriveSummary.start_time).where(
            DriveSummary.start_time.is_not(None),
        ),
    ).all()

    priorDriveCount = 0
    newDriveCount = 0
    unresolved: list[int] = []
    overlapping: list[int] = []
    for sourceId, startTime in drives:
        matches = [
            e for e in eras
            if e.ecu_install_timestamp_utc <= startTime
            and (
                e.ecu_removal_timestamp_utc is None
                or e.ecu_removal_timestamp_utc >= startTime
            )
        ]
        if not matches:
            unresolved.append(sourceId)
        elif len(matches) > 1:
            overlapping.append(sourceId)
        elif matches[0].ecu_signature == newSignature:
            newDriveCount += 1
        else:
            priorDriveCount += 1

    return {
        "priorSignature": priorSignature,
        "newSignature": newSignature,
        "priorDriveCount": priorDriveCount,
        "newDriveCount": newDriveCount,
        "unresolved": unresolved,
        "overlapping": overlapping,
    }


if __name__ == "__main__":
    sys.exit(main())
