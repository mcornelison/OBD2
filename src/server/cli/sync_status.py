################################################################################
# File Name: sync_status.py
# Purpose/Description: US-795(a) -- print what the server knows about each
#                      car's sync queue, one line per car. Read-only.
# Author: Atlas (Architect) -- US-795(a), CIO-directed build
# Creation Date: 2026-10-06
################################################################################
"""Sync-queue status CLI (US-795(a)).

Usage::

    python -m src.server.cli.sync_status [--device DEVICE_ID]

One line per car that has ever completed a sync contact::

    <device>: last contact <ts> (<age> ago): N queued (exact | at least)
              - drive D, sensor S; nothing known since [| ALARM: ...]

The server cannot see rows created after the last contact, so it states what
was true then and says nothing about now. This is a pure reader.
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from src.server.cli._ecu_lineage_support import resolveSyncDatabaseUrl
from src.server.services.sync_status import readSyncStatus

EXIT_OK = 0


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.server.cli.sync_status",
        description="State each car's sync queue as of its last contact.",
    )
    parser.add_argument(
        "--device",
        dest="device",
        default=None,
        help="Only this device id (default: every device that has synced).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m src.server.cli.sync_status``."""
    args = _buildArgParser().parse_args(argv)
    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    try:
        with Session(engine) as session:
            statuses = readSyncStatus(session, now=datetime.now(UTC), deviceId=args.device)
    finally:
        engine.dispose()

    if not statuses:
        print("no sync contact recorded for any device")
        return EXIT_OK
    for status in statuses:
        print(f"{status.deviceId}: {status.statement}")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
