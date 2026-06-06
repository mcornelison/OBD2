################################################################################
# File Name: add_ecu_note.py
# Purpose/Description: F-108 (US-366) server CLI appending a timestamped line to
#                      a vehicle_info row's `notes` column.  `notes` is a MUTABLE
#                      column (distinct from the immutable ECU-identity columns),
#                      and the append is history-preserving: prior lines are
#                      never overwritten.  A bogus --vehicle-info-id is a graceful
#                      error with no partial state.  Graceful on a pre-v0010 DB.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- append-only notes CLI.
# ================================================================================
################################################################################

"""F-108 ECU-note appender CLI (US-366).

Appends a timestamped line to a vehicle_info row's ``notes`` so CIO + Spool can
annotate an ECU (e.g. "Mode 22 silent", "knock retard observed") without raw
SQL.  Appends are history-preserving; prior content is never overwritten.

Usage::

    python -m server.cli.add_ecu_note --vehicle-info-id 2 \\
        --text "Mode 22 silent 2026-05-22"

Per US-366 conditionalOutcome, a bare-overwrite mode is intentionally NOT
provided here; prefix-namespacing of notes (e.g. [KNOCK]/[CAL_DRIFT]) is a
separate ergonomics Story.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.server.cli._ecu_lineage_support import (
    PRE_MIGRATION_MESSAGE,
    appendNote,
    ecuLineageColumnsPresent,
    resolveSyncDatabaseUrl,
)
from src.server.db.models import VehicleInfo

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 1
EXIT_RUNTIME = 2


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.cli.add_ecu_note",
        description="Append a timestamped note to a vehicle_info row.",
    )
    parser.add_argument(
        "--vehicle-info-id",
        required=True,
        type=int,
        metavar="ID",
        help="vehicle_info.id to annotate.",
    )
    parser.add_argument(
        "--text",
        required=True,
        metavar="TEXT",
        help="Note text to append (a UTC-timestamped line).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m server.cli.add_ecu_note``."""
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    try:
        if not ecuLineageColumnsPresent(engine):
            logger.error("add_ecu_note | ERROR | %s", PRE_MIGRATION_MESSAGE)
            return EXIT_CONFIG

        with Session(engine) as session:
            row = session.get(VehicleInfo, args.vehicle_info_id)
            if row is None:
                logger.error(
                    "add_ecu_note | ERROR | vehicle_info id %s not found; "
                    "no note written.", args.vehicle_info_id,
                )
                return EXIT_RUNTIME

            row.notes = appendNote(
                row.notes, args.text, now=datetime.now(UTC),
            )
            session.commit()
            logger.info(
                "add_ecu_note | OK | appended note to vehicle_info id %s",
                args.vehicle_info_id,
            )
            return EXIT_OK
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
