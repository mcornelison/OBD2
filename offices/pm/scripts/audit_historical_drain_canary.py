#!/usr/bin/env python3
################################################################################
# File Name: audit_historical_drain_canary.py
# Purpose/Description: V0.27.11 US-343 -- re-audit drains 10-22 (V0.24.1
#                      deploy 2026-05-04 onward) using the *honest* canary
#                      semantics. Pre-fix the boot_reason ladder probe
#                      matched the orchestrator INTENT marker and lied
#                      "clean=1" on every hard-crash. This script reads
#                      Pi-side startup_log + journalctl boot-archive and
#                      emits a corrected per-drain verdict.
#
#                      Read-only: no UPDATE, no DELETE, no INSERT against
#                      live tables. Writes a Markdown findings document to
#                      offices/pm/findings/2026-05-15-drain-10-22-canary-
#                      re-audit.md when --output is given.
#
# Usage:
#   python offices/pm/scripts/audit_historical_drain_canary.py --dry-run
#   python offices/pm/scripts/audit_historical_drain_canary.py \
#       --output offices/pm/findings/2026-05-15-drain-10-22-canary-re-audit.md
#
# Author: Ralph (US-343)
# Creation Date: 2026-05-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
################################################################################

"""US-343 historical drain canary re-audit.

Connects to chi-eclipse-01 via SSH (using the same deploy/addresses.sh
conventions as deploy-pi.sh), reads startup_log rows from the Pi-side
SQLite DB, and for each prior_boot_id checks the boot's journal for
the SUCCESS marker that V0.27.11 makes authoritative. Emits a verdict
per drain:

* graceful: success marker present in prior-boot journal
* hard-crash: success marker absent AND TRIGGER intent marker present
* indeterminate: neither marker present (journal pruned, drain
  manually aborted, etc.)

The corrected verdicts let Marcus update F-008 / F-012
regression_manifest lastValidated and re-grade historical drain
pass/fail.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# Markers we re-audit against. SUCCESS_MARKER is coupled to the canonical
# src.pi.hardware.shutdown_handler.SHUTDOWN_SUCCESS_MARKER via a guarded
# import so it cannot silently drift the way the live canary did
# pre-V0.27.11. The literal fallback exists ONLY for the PM-tooling
# context where the project venv (and thus src.*) is not on the path.
try:
    from src.pi.hardware.shutdown_handler import SHUTDOWN_SUCCESS_MARKER as _SM
    SUCCESS_MARKER = _SM
except Exception:  # noqa: BLE001 -- PM tooling may run outside the project venv
    SUCCESS_MARKER = "PowerDownOrchestrator: poweroff accepted by systemd"
INTENT_MARKER = "PowerDownOrchestrator: TRIGGER at"  # historical-only: the
# orchestrator _enterTrigger log line (a log string, not an exported constant);
# kept as a documented literal for the drains-10-22 historical re-audit grep.

# Drains 10-22 deployed under V0.24.1 (2026-05-04 onward). V0.27.11 is
# the first deploy with an honest canary.
AUDIT_SINCE = "2026-05-04"

DEFAULT_PI_HOST = "chi-eclipse-01"  # SSH config alias -> 10.27.27.28
DEFAULT_PI_USER = "mcornelison"
DEFAULT_DB_PATH = "/home/mcornelison/Projects/Eclipse-01/data/obd.db"


@dataclass(slots=True)
class DrainVerdict:
    drainNumber: int | None
    bootId: str
    priorBootClean: int | None
    successMarkerFound: bool
    intentMarkerFound: bool
    verdict: str  # 'graceful' | 'hard-crash' | 'indeterminate'


def runSsh(piHost: str, piUser: str, remoteCmd: str, *, dryRun: bool) -> str:
    """Run a remote command on the Pi via SSH; return stdout."""
    cmd = ["ssh", f"{piUser}@{piHost}", remoteCmd]
    if dryRun:
        print(f"[dry-run] ssh {piUser}@{piHost} {remoteCmd!r}")
        return ""
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        print(
            f"WARNING: ssh exited {result.returncode}: {result.stderr.strip()}",
            file=sys.stderr,
        )
    return result.stdout


def readStartupLogRows(piHost: str, piUser: str, dbPath: str, *, dryRun: bool):
    """Read all startup_log rows where the prior boot is in audit range."""
    sqlite = (
        f"sqlite3 -json {dbPath} "
        f"\"SELECT boot_id, prior_boot_clean, prior_last_entry_ts "
        f"FROM startup_log WHERE prior_last_entry_ts >= '{AUDIT_SINCE}' "
        f"ORDER BY recorded_at;\""
    )
    raw = runSsh(piHost, piUser, sqlite, dryRun=dryRun)
    if not raw.strip():
        return []
    return json.loads(raw)


def probeBootForMarker(
    piHost: str, piUser: str, bootId: str, marker: str, *, dryRun: bool
) -> bool:
    """Grep the prior boot's journal for an exact marker substring."""
    journalctl = (
        f"sudo journalctl -b '{bootId}' --no-pager | "
        f"grep -F -q -- '{marker}'"
    )
    if dryRun:
        runSsh(piHost, piUser, journalctl, dryRun=True)
        return False
    result = subprocess.run(
        ["ssh", f"{piUser}@{piHost}", journalctl],
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0


def auditRows(rows, piHost, piUser, *, dryRun: bool) -> list[DrainVerdict]:
    verdicts: list[DrainVerdict] = []
    for idx, row in enumerate(rows, start=10):
        bootId = row.get("boot_id", "")
        priorClean = row.get("prior_boot_clean")
        if not bootId:
            continue
        successFound = probeBootForMarker(
            piHost, piUser, bootId, SUCCESS_MARKER, dryRun=dryRun
        )
        intentFound = probeBootForMarker(
            piHost, piUser, bootId, INTENT_MARKER, dryRun=dryRun
        )
        if successFound:
            verdict = "graceful"
        elif intentFound:
            verdict = "hard-crash"
        else:
            verdict = "indeterminate"
        verdicts.append(DrainVerdict(
            drainNumber=idx,
            bootId=bootId,
            priorBootClean=priorClean,
            successMarkerFound=successFound,
            intentMarkerFound=intentFound,
            verdict=verdict,
        ))
    return verdicts


def writeFindings(verdicts: list[DrainVerdict], outPath: Path) -> None:
    lines = [
        "# US-343 Drain 10-22 Canary Re-Audit Findings",
        "",
        "**Audit date:** 2026-05-15",
        f"**Audit since:** {AUDIT_SINCE} (V0.24.1 deploy)",
        "**Generated by:** offices/pm/scripts/audit_historical_drain_canary.py",
        "",
        "| Drain | boot_id (first 8) | prior_boot_clean (stored) | "
        "success marker | intent marker | corrected verdict |",
        "|------:|:------------------|--------------------------:|"
        ":--------------:|:-------------:|:------------------|",
    ]
    for v in verdicts:
        lines.append(
            f"| {v.drainNumber} | `{v.bootId[:8]}` | {v.priorBootClean} | "
            f"{'Y' if v.successMarkerFound else 'N'} | "
            f"{'Y' if v.intentMarkerFound else 'N'} | **{v.verdict}** |"
        )
    lines.extend([
        "",
        "## Interpretation",
        "",
        "* **graceful** -- success marker present in prior-boot journal.",
        "* **hard-crash** -- intent marker present, success marker absent. The",
        "  V0.24.1 ladder TRIGGERed but systemctl poweroff failed (I-036",
        "  PolicyKit denial) -- Pi continued running on residual battery",
        "  until buck-dropout floor (~3.30V).",
        "* **indeterminate** -- neither marker present in audited window",
        "  (journal pruned, drain manually aborted, V0.27.11 success marker",
        "  not yet shipped at the time of drain, etc.).",
        "",
        "## F-008 / F-012 regression_manifest implications",
        "",
        "Drains marked 'graceful' here remain valid validations of the",
        "V0.24.1 graceful-shutdown ladder. Drains marked 'hard-crash'",
        "must be re-validated post-V0.27.11 deploy (Drain 23+). Drains",
        "marked 'indeterminate' need PM judgement call (verify against",
        "drain bench notes).",
    ])
    outPath.parent.mkdir(parents=True, exist_ok=True)
    outPath.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="US-343 historical drain canary re-audit"
    )
    parser.add_argument("--pi-host", default=DEFAULT_PI_HOST)
    parser.add_argument("--pi-user", default=DEFAULT_PI_USER)
    parser.add_argument("--db-path", default=DEFAULT_DB_PATH)
    parser.add_argument(
        "--output", type=Path, default=None,
        help="Path to write findings Markdown. Stdout if omitted.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print SSH commands without executing.",
    )
    args = parser.parse_args()

    rows = readStartupLogRows(
        args.pi_host, args.pi_user, args.db_path, dryRun=args.dry_run
    )
    verdicts = auditRows(
        rows, args.pi_host, args.pi_user, dryRun=args.dry_run
    )

    if args.output:
        writeFindings(verdicts, args.output)
        print(f"Findings written to {args.output}")
    else:
        for v in verdicts:
            print(
                f"Drain {v.drainNumber}: boot={v.bootId[:8]} "
                f"stored={v.priorBootClean} -> {v.verdict}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
