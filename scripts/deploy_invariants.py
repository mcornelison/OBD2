################################################################################
# File Name: deploy_invariants.py
# Purpose/Description: US-389 single-instance matched-pair deploy invariant
#                      (F-107 Root 1 closure, Atlas C-5). The orchestrator's
#                      single-instance guard config flag
#                      (pi.runtime.singleInstanceGuard.enabled) and the systemd
#                      RuntimeDirectory=eclipse-obd are a MATCHED PAIR: enabling
#                      the guard WITHOUT RuntimeDirectory makes the non-root
#                      service hit EPERM on mkdir(/run/eclipse-obd) and
#                      crash-loop on boot; shipping RuntimeDirectory WITHOUT the
#                      guard leaves the dual-process attribution defect
#                      un-prevented. This module reads both halves and FAILS
#                      LOUDLY (non-zero exit / raised exception) when either is
#                      missing, so deploy-pi.sh can refuse the deploy before it
#                      touches the Pi. Also summarizes the live state for the
#                      .deploy-version stamp (no longer silent-on-top-of V0.28.2).
# Author: Rex (Ralph Agent)
# Creation Date: 2026-06-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-28    | Rex (US-389) | Initial -- matched-pair assertion + summary
#               |              | helper; CLI check-pair / summarize subcommands
#               |              | the deploy script shells out to.
# ================================================================================
################################################################################

"""Single-instance matched-pair deploy invariant (US-389, F-107 Root 1).

Public API:
    readGuardEnabled(configPath) -> bool | None
    readUnitRuntimeDirectory(unitPath) -> str | None
    summarizeSingleInstanceState(configPath, unitPath) -> dict
    assertMatchedPair(configPath, unitPath, *, expectedRuntimeDirectory=...) -> None

CLI:
    python scripts/deploy_invariants.py check-pair --config config.json \\
        --unit deploy/eclipse-obd.service
        -> exit 0 if the matched pair is intact; exit 1 + loud stderr if either
           half is missing; exit 2 if a required file is unreadable.

    python scripts/deploy_invariants.py summarize --config config.json \\
        --unit deploy/eclipse-obd.service
        -> prints {"guardEnabled": <bool|null>, "runtimeDirectory": <str|null>}
           for embedding into the .deploy-version release record.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

__all__ = [
    "MatchedPairViolation",
    "EXPECTED_RUNTIME_DIRECTORY",
    "readGuardEnabled",
    "readUnitRuntimeDirectory",
    "summarizeSingleInstanceState",
    "assertMatchedPair",
]

# The systemd RuntimeDirectory= value that pairs with the guard's lockPath
# (/run/eclipse-obd/orchestrator.lock). systemd creates /run/eclipse-obd owned
# by User= on start so the non-root orchestrator can write its pidfile lock.
EXPECTED_RUNTIME_DIRECTORY = "eclipse-obd"

# Matches a non-commented `RuntimeDirectory=<value>` line in a systemd unit.
# Leading whitespace tolerated; value is the first whitespace-delimited token
# (systemd allows a space-separated list, but the orchestrator uses exactly one).
_RUNTIME_DIR_RE = re.compile(r"^\s*RuntimeDirectory\s*=\s*(\S+)", re.MULTILINE)


class MatchedPairViolation(RuntimeError):
    """Raised when the guard flag / RuntimeDirectory matched pair is broken."""


def readGuardEnabled(configPath: str | Path) -> bool | None:
    """Read pi.runtime.singleInstanceGuard.enabled from config.json.

    Args:
        configPath: Path to config.json.

    Returns:
        The boolean flag value, or None if the singleInstanceGuard block (or
        its enabled key) is absent entirely.

    Raises:
        FileNotFoundError: config file does not exist.
        ValueError: config file is not valid JSON.
    """
    p = Path(configPath)
    if not p.is_file():
        raise FileNotFoundError(f"config file not found: {p}")
    try:
        config = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p}: invalid JSON ({exc})") from exc
    guard = (
        config.get("pi", {})
        .get("runtime", {})
        .get("singleInstanceGuard", {})
    )
    if "enabled" not in guard:
        return None
    return bool(guard["enabled"])


def readUnitRuntimeDirectory(unitPath: str | Path) -> str | None:
    """Read the RuntimeDirectory= value from a systemd unit file.

    Args:
        unitPath: Path to the .service file.

    Returns:
        The RuntimeDirectory value (e.g. "eclipse-obd"), or None if no
        non-commented RuntimeDirectory= directive is present.

    Raises:
        FileNotFoundError: unit file does not exist.
    """
    p = Path(unitPath)
    if not p.is_file():
        raise FileNotFoundError(f"unit file not found: {p}")
    text = p.read_text(encoding="utf-8")
    # Strip comment lines so a documentation reference like
    #   "# RuntimeDirectory=eclipse-obd ..." doesn't read as the directive.
    uncommented = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )
    match = _RUNTIME_DIR_RE.search(uncommented)
    return match.group(1) if match else None


def summarizeSingleInstanceState(
    configPath: str | Path, unitPath: str | Path
) -> dict:
    """Summarize the live single-instance matched-pair state for the deploy stamp.

    Args:
        configPath: Path to config.json.
        unitPath: Path to the eclipse-obd.service unit.

    Returns:
        {"guardEnabled": bool | None, "runtimeDirectory": str | None}
    """
    return {
        "guardEnabled": readGuardEnabled(configPath),
        "runtimeDirectory": readUnitRuntimeDirectory(unitPath),
    }


def assertMatchedPair(
    configPath: str | Path,
    unitPath: str | Path,
    *,
    expectedRuntimeDirectory: str = EXPECTED_RUNTIME_DIRECTORY,
) -> None:
    """Assert the guard flag + RuntimeDirectory matched pair is intact.

    Args:
        configPath: Path to config.json.
        unitPath: Path to the eclipse-obd.service unit.
        expectedRuntimeDirectory: The RuntimeDirectory value the lock path
            requires (default "eclipse-obd").

    Raises:
        MatchedPairViolation: If the guard is not enabled OR the unit's
            RuntimeDirectory is missing / does not match the expected value.
            The message names BOTH the missing half and the consequence so a
            failed deploy is self-explanatory.
        FileNotFoundError: A required file is missing.
    """
    guardEnabled = readGuardEnabled(configPath)
    runtimeDirectory = readUnitRuntimeDirectory(unitPath)

    problems = []
    if guardEnabled is not True:
        problems.append(
            f"pi.runtime.singleInstanceGuard.enabled is {guardEnabled!r} "
            f"(expected True) in {configPath}"
        )
    if runtimeDirectory != expectedRuntimeDirectory:
        problems.append(
            f"RuntimeDirectory is {runtimeDirectory!r} "
            f"(expected {expectedRuntimeDirectory!r}) in {unitPath}"
        )

    if problems:
        raise MatchedPairViolation(
            "single-instance matched-pair invariant VIOLATED (US-389 / Atlas C-5): "
            + "; ".join(problems)
            + ". These are a MATCHED PAIR: enabling the guard without "
            "RuntimeDirectory crash-loops the non-root orchestrator (EPERM on "
            "mkdir /run/eclipse-obd); shipping RuntimeDirectory without the guard "
            "leaves the dual-process attribution defect (Root 1) un-prevented. "
            "Neither ships without the other."
        )


# ---- CLI ------------------------------------------------------------------


def _runCheckPair(args: argparse.Namespace) -> int:
    try:
        assertMatchedPair(args.config, args.unit)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except MatchedPairViolation as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        "OK: single-instance matched pair intact "
        f"(guard enabled + RuntimeDirectory={EXPECTED_RUNTIME_DIRECTORY})."
    )
    return 0


def _runSummarize(args: argparse.Namespace) -> int:
    summary = summarizeSingleInstanceState(args.config, args.unit)
    print(json.dumps(summary))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="US-389 single-instance matched-pair deploy invariant."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    check = sub.add_parser(
        "check-pair",
        help="Fail (exit non-zero) if the guard flag / RuntimeDirectory pair is broken.",
    )
    check.add_argument("--config", required=True, help="Path to config.json")
    check.add_argument("--unit", required=True, help="Path to eclipse-obd.service")

    summarize = sub.add_parser(
        "summarize",
        help="Print {guardEnabled, runtimeDirectory} JSON for the .deploy-version stamp.",
    )
    summarize.add_argument("--config", required=True, help="Path to config.json")
    summarize.add_argument("--unit", required=True, help="Path to eclipse-obd.service")

    args = parser.parse_args(argv)
    if args.cmd == "check-pair":
        return _runCheckPair(args)
    if args.cmd == "summarize":
        return _runSummarize(args)
    parser.error(f"unknown subcommand: {args.cmd}")
    return 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
