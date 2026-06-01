################################################################################
# File Name: show_ecu_lineage.py
# Purpose/Description: F-108 (US-366) server CLI listing the full append-only
#                      vehicle_info ECU lineage as a text table, ordered by
#                      install timestamp, with the currently-active ECU
#                      (ecu_removal_timestamp_utc IS NULL) highlighted.  Pure
#                      reader: no DB writes.  Graceful on an empty table ("no
#                      ECU lineage recorded yet") and on a pre-v0010 DB.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-366) | Initial -- ECU-lineage reader CLI.
# ================================================================================
################################################################################

"""F-108 ECU-lineage reader CLI (US-366).

Prints every historical ECU stamp in install-timestamp order so CIO + Spool
can audit the swap history from the command line.

Usage::

    python -m server.cli.show_ecu_lineage

The currently-active ECU (the row with ``ecu_removal_timestamp_utc IS NULL``)
is flagged ``ACTIVE``; closed rows show their removal instant.  This is a pure
reader -- it never writes.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.cli._ecu_lineage_support import (
    PRE_MIGRATION_MESSAGE,
    ecuLineageColumnsPresent,
    resolveSyncDatabaseUrl,
)
from src.server.db.models import VehicleInfo

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_CONFIG = 1

_EMPTY_MESSAGE = "no ECU lineage recorded yet"
_OPEN = "(active)"


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.cli.show_ecu_lineage",
        description="List the append-only vehicle_info ECU lineage.",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging.",
    )
    return parser


def _formatTimestamp(value) -> str:
    """Render a datetime as a compact UTC string, or a dash when NULL."""
    if value is None:
        return _OPEN
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _renderRow(row: VehicleInfo) -> str:
    active = row.ecu_removal_timestamp_utc is None
    marker = "ACTIVE" if active else "closed"
    return (
        f"  [{marker:^6}] id={row.id} "
        f"signature={row.ecu_signature} "
        f"cal={row.cal_signature or '-'} "
        f"install={_formatTimestamp(row.ecu_install_timestamp_utc)} "
        f"removal={_formatTimestamp(row.ecu_removal_timestamp_utc)}"
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m server.cli.show_ecu_lineage``."""
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    try:
        if not ecuLineageColumnsPresent(engine):
            logger.error("show_ecu_lineage | ERROR | %s", PRE_MIGRATION_MESSAGE)
            return EXIT_CONFIG

        with Session(engine) as session:
            rows = list(
                session.execute(
                    select(VehicleInfo).order_by(
                        VehicleInfo.ecu_install_timestamp_utc
                    )
                ).scalars()
            )

            if not rows:
                print(_EMPTY_MESSAGE)
                return EXIT_OK

            print("ECU lineage (oldest install first):")
            for row in rows:
                print(_renderRow(row))
            return EXIT_OK
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
