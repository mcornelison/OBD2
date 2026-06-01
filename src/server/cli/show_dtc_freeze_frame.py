################################################################################
# File Name: show_dtc_freeze_frame.py
# Purpose/Description: F-109 (US-369) server CLI that prints a DTC's Mode 02
#                      freeze-frame: the dtc_log row (code + timestamp), the
#                      freeze-frame's captured_at + 16-PID dictionary, and the
#                      vehicle_info row joined through the stored FK (the ECU era
#                      active at capture time -- Q4 round-trip, unchanged by
#                      later stamp_ecu_swap rows).  Pure reader: no DB writes.
#                      Graceful on a DTC with no freeze-frame ("no freeze-frame
#                      recorded for this DTC", exit 0) and on degraded captures
#                      (Mode 02 unavailable -> pid_responses_json={}).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-05-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-28    | Rex (US-369) | Initial -- freeze-frame reader CLI.
# ================================================================================
################################################################################

"""F-109 freeze-frame reader CLI (US-369).

Usage::

    python -m server.cli.show_dtc_freeze_frame --dtc-log-id N

Prints the DTC, its Mode 02 freeze-frame (16-PID snapshot), and the
``vehicle_info`` row the freeze-frame's FK points at -- the ECU that was
installed when the snapshot was captured.  The FK is bound once, at sync time,
by the capture-time ECU window (see ``src/server/api/sync.py``), so this reader
follows the stored FK and never re-resolves to the currently-active ECU (the Q4
round-trip).  This is a pure reader -- it never writes.
"""

from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from src.server.cli._ecu_lineage_support import resolveSyncDatabaseUrl
from src.server.db.models import DtcFreezeFrame, DtcLog, VehicleInfo

logger = logging.getLogger(__name__)

EXIT_OK = 0

_NO_FREEZE_FRAME = "no freeze-frame recorded for this DTC"
_MODE_02_UNAVAILABLE = "freeze-frame captured but Mode 02 PIDs unavailable"


def _buildArgParser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m server.cli.show_dtc_freeze_frame",
        description="Print a DTC's Mode 02 freeze-frame + the ECU active at capture time.",
    )
    parser.add_argument(
        "--dtc-log-id",
        type=int,
        required=True,
        dest="dtc_log_id",
        help="Server dtc_log.id whose freeze-frame should be shown.",
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
        return "-"
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def _printDtc(dtc: DtcLog | None, dtcLogId: int) -> None:
    if dtc is None:
        print(f"DTC log id {dtcLogId}: (no dtc_log row found)")
        return
    print(
        f"DTC {dtc.dtc_code} [{dtc.status}] "
        f"first_seen={_formatTimestamp(dtc.first_seen_timestamp)}"
    )


def _printFreezeFrame(frame: DtcFreezeFrame) -> None:
    print(f"  captured_at={_formatTimestamp(frame.captured_at_timestamp_utc)}")
    pids = frame.pid_responses_json or {}
    if not pids:
        print(f"  {_MODE_02_UNAVAILABLE}")
        if frame.notes:
            print(f"  notes: {frame.notes}")
        return
    print(f"  freeze-frame PIDs ({len(pids)}):")
    for name in sorted(pids):
        print(f"    {name} = {pids[name]}")
    if frame.notes:
        print(f"  notes: {frame.notes}")


def _printVehicleInfo(session: Session, frame: DtcFreezeFrame) -> None:
    if frame.vehicle_info_id is None:
        print("  ECU (vehicle_info): unresolved (vehicle_info_id IS NULL)")
        return
    vehicle = session.get(VehicleInfo, frame.vehicle_info_id)
    if vehicle is None:
        print(f"  ECU (vehicle_info id {frame.vehicle_info_id}): not found")
        return
    print(
        f"  ECU (vehicle_info id {vehicle.id}): "
        f"signature={vehicle.ecu_signature} "
        f"cal={vehicle.cal_signature or '-'} "
        f"install={_formatTimestamp(vehicle.ecu_install_timestamp_utc)} "
        f"removal={_formatTimestamp(vehicle.ecu_removal_timestamp_utc)}"
    )


def main(argv: list[str] | None = None) -> int:
    """Entry point for ``python -m server.cli.show_dtc_freeze_frame``."""
    parser = _buildArgParser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    )

    engine = create_engine(resolveSyncDatabaseUrl(), future=True)
    try:
        with Session(engine) as session:
            frames = list(
                session.execute(
                    select(DtcFreezeFrame)
                    .where(DtcFreezeFrame.dtc_log_id == args.dtc_log_id)
                    .order_by(DtcFreezeFrame.captured_at_timestamp_utc.desc())
                ).scalars()
            )

            if not frames:
                print(_NO_FREEZE_FRAME)
                return EXIT_OK

            if len(frames) > 1:
                # conditionalOutcome 3: show the most recent + a loud WARNING
                # rather than silently dropping the older captures.
                logger.warning(
                    "multiple freeze-frames (%d) for dtc_log_id %s; showing "
                    "most recent by captured_at",
                    len(frames), args.dtc_log_id,
                )

            frame = frames[0]
            dtc = session.get(DtcLog, args.dtc_log_id)
            _printDtc(dtc, args.dtc_log_id)
            _printFreezeFrame(frame)
            _printVehicleInfo(session, frame)
            return EXIT_OK
    finally:
        engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
