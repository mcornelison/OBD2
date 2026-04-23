################################################################################
# File Name: report.py
# Purpose/Description: CLI report tool for the crawl-phase server.  Wraps the
#                      drive and trend report builders so the CIO can SSH into
#                      Chi-Srv-01 and inspect analytics output.
# Author: Ralph Agent
# Creation Date: 2026-04-16
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-16    | Ralph Agent  | Initial implementation for US-160 (Sprint 7)
# 2026-04-16    | Ralph Agent  | US-162 (Sprint 9) — --calibrate / --apply
#               |              | modes for real-vs-sim baseline calibration.
# 2026-04-21    | Rex (Ralph)  | US-219 — added ``--drive-id`` alias so the
#               |              | post-drive review wrapper can invoke
#               |              | ``report.py --drive-id N`` consistently with
#               |              | the spool_prompt_invoke.py CLI surface.
# ================================================================================
################################################################################

"""
CLI report tool for the Eclipse OBD-II server (crawl phase).

Usage::

    # Latest drive report
    python scripts/report.py --drive latest

    # Drive report for a specific date (first drive on that day)
    python scripts/report.py --drive 2026-04-15

    # Summary table of all drives
    python scripts/report.py --drive all

    # Rolling trend report (default 10-drive window)
    python scripts/report.py --trends

    # Trend report over last N drives
    python scripts/report.py --trends --last 20

    # Propose baseline calibration from real drives (pure read)
    python scripts/report.py --calibrate --device chi-eclipse-01

    # Apply proposed baselines atomically (CIO approval)
    python scripts/report.py --calibrate --apply --device chi-eclipse-01

The ``--db-url`` flag overrides the default SQLAlchemy URL, which is read
from the ``DATABASE_URL`` environment variable.  For local testing,
point it at a SQLite file produced by :mod:`scripts.load_data`.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure project root is importable (matches scripts/load_data.py).
# ---------------------------------------------------------------------------
_SCRIPT_DIR = Path(__file__).resolve().parent
_PROJECT_ROOT = _SCRIPT_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.engine import Engine  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.server.analytics import calibration as _calibration  # noqa: E402
from src.server.reports.drive_report import (  # noqa: E402
    buildAllDrivesReport,
    buildDriveReport,
)
from src.server.reports.trend_report import (  # noqa: E402
    DEFAULT_TREND_PARAMETERS,
    buildTrendReport,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB_URL_ENV: str = "DATABASE_URL"
_DEFAULT_DB_URL_FALLBACK: str = "sqlite:///data/server_crawl.db"


def _toSyncDriverUrl(url: str) -> str:
    # Async drivers (aiomysql) raise MissingGreenlet under a sync engine.
    # The .env file uses the async URL for the FastAPI server; rewrite for CLI use.
    return url.replace("+aiomysql://", "+pymysql://", 1)


# ==============================================================================
# CLI parsing
# ==============================================================================


def parseArguments(argv: list[str] | None = None) -> argparse.Namespace:
    """
    Parse CLI arguments.

    Exposes two mutually exclusive report modes (``--drive`` and ``--trends``)
    plus the ``--last`` window override and a database URL override.

    Args:
        argv: Optional argv slice for testing; defaults to ``sys.argv[1:]``.

    Returns:
        Populated ``argparse.Namespace``.
    """
    parser = argparse.ArgumentParser(
        prog="report.py",
        description="Print analytics reports for the Eclipse OBD-II server.",
    )

    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--drive",
        "--drive-id",
        dest="drive",
        metavar="REF",
        help=(
            "Report on a single drive.  REF is 'latest', 'all', a "
            "YYYY-MM-DD date, or a drive id.  ``--drive-id`` is an alias "
            "for the review-ritual wrapper (US-219)."
        ),
    )
    mode.add_argument(
        "--trends",
        action="store_true",
        help="Print the rolling trend report.",
    )
    mode.add_argument(
        "--calibrate",
        action="store_true",
        help=(
            "Propose baseline updates from real drives.  Pure read unless "
            "combined with --apply, which writes approved baselines."
        ),
    )

    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            "Write proposed baselines atomically.  Only valid with "
            "--calibrate."
        ),
    )
    parser.add_argument(
        "--device",
        default=None,
        metavar="DEVICE",
        help=(
            "Filter by device id (e.g. chi-eclipse-01).  Required with "  # b044-exempt: argparse help prose
            "--calibrate --apply; optional with --calibrate alone."
        ),
    )
    parser.add_argument(
        "--last",
        type=int,
        default=None,
        metavar="N",
        help=(
            "Override the rolling trend window size (default: 10 drives). "
            "Only applies with --trends."
        ),
    )
    parser.add_argument(
        "--db-url",
        default=None,
        metavar="URL",
        help=(
            "SQLAlchemy database URL.  Falls back to the "
            f"${_DEFAULT_DB_URL_ENV} environment variable, then "
            f"'{_DEFAULT_DB_URL_FALLBACK}'."
        ),
    )

    args = parser.parse_args(argv)
    if args.apply and not args.calibrate:
        parser.error("--apply requires --calibrate")
    if args.calibrate and args.apply and args.device is None:
        parser.error("--calibrate --apply requires --device")
    return args


# ==============================================================================
# Rendering
# ==============================================================================


def renderReport(
    args: argparse.Namespace,
    engine: Engine,
) -> str:
    """
    Dispatch to the appropriate report builder.

    Args:
        args: Parsed CLI namespace.
        engine: SQLAlchemy engine bound to the server database.

    Returns:
        The fully-formatted report string.
    """
    with Session(engine) as session:
        if args.trends:
            windowSize = args.last if args.last is not None else 10
            return buildTrendReport(
                session,
                windowSize=windowSize,
                parameters=DEFAULT_TREND_PARAMETERS,
            )

        if args.calibrate:
            return _renderCalibration(session, args)

        driveRef = args.drive
        if driveRef == "all":
            return buildAllDrivesReport(session)
        return buildDriveReport(session, driveRef)


# ==============================================================================
# Calibration rendering
# ==============================================================================


_BAR = "═" * 72
_RULE = "─" * 72


def _renderCalibration(
    session: Session,
    args: argparse.Namespace,
) -> str:
    """
    Render ``--calibrate`` output (and optionally apply via ``--apply``).

    Pure read by default — never mutates ``baselines`` without ``--apply``.
    Returns a single formatted string; the CLI caller prints it verbatim.
    """
    result = _calibration.proposeCalibration(
        session, deviceId=args.device,
    )

    if result.realDriveCount < _calibration.MIN_REAL_DRIVES:
        missing = _calibration.MIN_REAL_DRIVES - result.realDriveCount
        return (
            f"{_BAR}\n"
            f"  Baseline Calibration — {result.realDriveCount} real drive(s)\n"
            f"{_BAR}\n\n"
            f"  Need {missing} more real drives before calibration is "
            f"meaningful.\n"
            f"  (Minimum: {_calibration.MIN_REAL_DRIVES} real drives.)\n"
            f"{_BAR}"
        )

    header = (
        f"{_BAR}\n"
        f"  Baseline Calibration — {result.realDriveCount} Real Drives "
        f"Available\n"
        f"{_BAR}\n\n"
    )

    if not result.proposals:
        return (
            header
            + "  All parameters within 2% of sim baseline — no updates "
            + "proposed.\n"
            + _BAR
        )

    lines: list[str] = [
        f"  {'Parameter':<16}{'Sim':>10}{'Real':>12}"
        f"{'Δ':>10}{'%':>8}  {'Action'}",
        f"  {_RULE[:70]}",
    ]
    for prop in result.proposals:
        deltaPct = (
            (prop.delta / prop.sim_value) * 100.0
            if prop.sim_value != 0.0
            else 0.0
        )
        lines.append(
            f"  {prop.parameter_name[:16]:<16}"
            f"{prop.sim_value:>10.2f}"
            f"{prop.real_value:>12.2f}"
            f"{prop.delta:>+10.2f}"
            f"{deltaPct:>+7.1f}%  "
            f"{prop.action}"
        )
    body = "\n".join(lines) + "\n\n"

    if args.apply:
        written = _calibration.applyCalibration(
            session, result.proposals, deviceId=args.device,
        )
        session.commit()
        footer = (
            f"  Applied {written} baseline(s) to device "
            f"'{args.device}'.\n{_BAR}"
        )
    else:
        footer = (
            "  Review these baselines before applying.\n"
            "  Run: python scripts/report.py --calibrate --apply "
            "--device <DEVICE>\n"
            f"{_BAR}"
        )

    return header + body + footer


def _resolveDbUrl(cliUrl: str | None) -> str:
    if cliUrl is not None:
        return cliUrl
    envUrl = os.environ.get(_DEFAULT_DB_URL_ENV)
    if envUrl:
        return envUrl
    return _DEFAULT_DB_URL_FALLBACK


# ==============================================================================
# Entry point
# ==============================================================================


def main(argv: list[str] | None = None) -> int:
    """
    CLI entry point.  Returns a Unix-style exit code.

    Exit codes:
        * 0 — report printed successfully.
        * 2 — invalid arguments (argparse already printed the reason).
    """
    args = parseArguments(argv)
    # Reports use box-drawing and arrow glyphs.  Windows consoles often default
    # to cp1252, which cannot encode them — reconfigure to UTF-8 when possible.
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):  # pragma: no cover - depends on stream
            pass

    dbUrl = _toSyncDriverUrl(_resolveDbUrl(args.db_url))
    engine = create_engine(dbUrl)
    try:
        output = renderReport(args, engine)
    finally:
        engine.dispose()
    print(output)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
