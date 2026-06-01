################################################################################
# File Name: stamp_ecu_swap.py
# Purpose/Description: F-108 (US-366) server CLI recording an ECU swap into the
#                      append-only vehicle_info lineage.  In a SINGLE DB
#                      transaction it CLOSES the currently-active row (sets
#                      ecu_removal_timestamp_utc = --as-of) and OPENS a new
#                      currently-active row (--signature / --cal-signature /
#                      install = --as-of).  Idempotent: re-stamping the same
#                      signature at the same instant is a no-op.  Refuses a
#                      same-signature-different-instant rewrite (no silent
#                      timestamp edit) and refuses --update-existing-signature
#                      outright (ECU-identity columns are append-only; the only
#                      sanctioned identity change is close+open).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- close+open ECU-swap writer CLI.
# ================================================================================
################################################################################

"""F-108 ECU-swap writer CLI (US-366).

Records an ECU swap by closing the currently-active ``vehicle_info`` row and
opening a new one, atomically.  Intended for CIO + Spool use when a physical
ECU change happens.

Usage::

    # Record a swap to a new ECU as of a precise instant:
    python -m server.cli.stamp_ecu_swap \\
        --signature MD335287-ECMLinkV3 --cal-signature pump-93-v1 \\
        --as-of 2026-05-22T14:00:00Z

    # Re-running the SAME signature + as-of is a safe no-op (idempotent).
    # Re-running the SAME signature with a DIFFERENT as-of is REFUSED
    # (it would silently rewrite the active row's install instant).

The ECU-identity columns (``ecu_signature``, ``ecu_install_timestamp_utc``)
are append-only: there is intentionally NO in-place identity edit.  The
``--update-existing-signature`` flag exists only to REFUSE that anti-pattern
with a documented error -- use a normal close+open swap instead.  This CLI is
the SOLE sanctioned mutator of the lineage; ad-hoc SQL UPDATEs bypass the
invariant and are an anti-pattern (see the vehicle_info table/model docstring).

This CLI does not bootstrap the FIRST lineage row (it has nothing to close);
that is the US-367 backfill script's job.  Run it against a DB with one
currently-active row.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.server.cli._ecu_lineage_support import (
    PRE_MIGRATION_MESSAGE,
    ecuLineageColumnsPresent,
    getActiveVehicleInfo,
    nextSourceId,
    parseIsoTimestamp,
    resolveSyncDatabaseUrl,
)
from src.server.db.models import VehicleInfo

logger = logging.getLogger(__name__)

# Exit codes (see Quality + Safety Constants): 0 success / 1 config / 2 runtime.
EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_RUNTIME = 2


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.cli.stamp_ecu_swap",
        description=(
            "Record an ECU swap: close the currently-active vehicle_info "
            "row + open a new one (append-only lineage)."
        ),
    )
    parser.add_argument(
        "--signature",
        required=True,
        metavar="ID",
        help="ECU signature of the newly-installed ECU.",
    )
    parser.add_argument(
        "--cal-signature",
        default=None,
        metavar="ID",
        help="Calibration signature of the new ECU (optional).",
    )
    parser.add_argument(
        "--as-of",
        required=True,
        metavar="ISO8601",
        help=(
            "Swap instant (ISO-8601, e.g. 2026-05-22T14:00:00Z): closes the "
            "prior row at this instant + installs the new row at it."
        ),
    )
    parser.add_argument(
        "--update-existing-signature",
        action="store_true",
        help=(
            "(REFUSED) ECU-identity columns are append-only; this flag only "
            "exists to reject in-place identity edits -- use close+open."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m server.cli.stamp_ecu_swap``."""
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    # Identity-immutability guard (US-365 AC#9): refuse in-place identity edits.
    if args.update_existing_signature:
        logger.error(
            "stamp_ecu_swap | REFUSED | ECU-identity columns are append-only; "
            "--update-existing-signature would rewrite history.  Use close+"
            "open semantics (a normal stamp_ecu_swap) instead.",
        )
        return EXIT_RUNTIME

    try:
        asOf = parseIsoTimestamp(args.as_of)
    except ValueError as exc:
        logger.error(
            "stamp_ecu_swap | ERROR | --as-of %r is not a valid ISO-8601 "
            "timestamp (%s)", args.as_of, exc,
        )
        return EXIT_RUNTIME

    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    try:
        if not ecuLineageColumnsPresent(engine):
            logger.error("stamp_ecu_swap | ERROR | %s", PRE_MIGRATION_MESSAGE)
            return EXIT_CONFIG

        with Session(engine) as session:
            return _stampSwap(
                session,
                signature=args.signature,
                calSignature=args.cal_signature,
                asOf=asOf,
            )
    finally:
        engine.dispose()


def _stampSwap(
    session: Session,
    *,
    signature: str,
    calSignature: str | None,
    asOf,
) -> int:
    """Close the active row + open a new one (single transaction)."""
    active = getActiveVehicleInfo(session)

    if active is None:
        logger.error(
            "stamp_ecu_swap | ERROR | no currently-active vehicle_info row to "
            "close.  Bootstrap the first row via the US-367 backfill script.",
        )
        return EXIT_RUNTIME

    # Idempotency / no-silent-rewrite (conditionalOutcomes 1 + 2).
    if active.ecu_signature == signature:
        if active.ecu_install_timestamp_utc == asOf:
            logger.info(
                "stamp_ecu_swap | no-op | signature=%s already stamped + "
                "active at install=%s; no change.", signature, asOf,
            )
            return EXIT_OK
        logger.error(
            "stamp_ecu_swap | ERROR | signature=%s is already active with "
            "install=%s; refusing to rewrite its install instant to %s "
            "(use a new signature to record a genuine swap).",
            signature, active.ecu_install_timestamp_utc, asOf,
        )
        return EXIT_RUNTIME

    # Atomic close + open.  Flush the CLOSE first so the active marker frees
    # up before the new active row is inserted (the unique marker index would
    # otherwise reject two active rows mid-flush) -- still ONE transaction, so
    # any failure rolls BOTH back and the single-active invariant is preserved.
    active.ecu_removal_timestamp_utc = asOf
    session.flush()
    session.add(
        VehicleInfo(
            # Server-authored lineage row: same device namespace as the prior
            # row, next free source_id to satisfy UNIQUE(source_device,
            # source_id) (the Pi never authors these rows).
            source_id=nextSourceId(session, active.source_device),
            source_device=active.source_device,
            vin=active.vin,
            ecu_signature=signature,
            cal_signature=calSignature,
            ecu_install_timestamp_utc=asOf,
            ecu_removal_timestamp_utc=None,
        )
    )
    session.commit()

    logger.info(
        "stamp_ecu_swap | OK | closed signature=%s at %s; opened "
        "signature=%s (cal=%s) install=%s",
        active.ecu_signature, asOf, signature, calSignature, asOf,
    )
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
