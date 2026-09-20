#!/usr/bin/env python3
################################################################################
# File Name: check_tier_parity.py
# Purpose/Description: ARCH-038 -- verify the DESTINATION exists, not just that
#   we sent. For every table under the sync contract, ask the server whether it
#   exists and how many rows it holds.
#
# WHY THIS EXISTS -- A-37, measured 2026-09-16
#   EDR persistence shipped 2026-07-01. The server tables were NEVER CREATED.
#   `SHOW TABLES LIKE 'edr%'` on obd2db returned 0 rows, while the Pi journal
#   purged ~1.77M rows/day on an age-only rule. Six to ten weeks of capture
#   recorded itself and deleted itself into a destination that did not exist.
#   All EDR older than 2026-09-07 is gone and none of it ever synced.
#
#   Every component was working correctly. The reader read, the subscriber
#   persisted, the purge honoured its configured window. The defect lived in
#   the SEAM nobody owned -- which is precisely what component tests miss.
#
#   A destination at ZERO for a producer at MILLIONS is not a subtle signal.
#   This script is the one-line question nobody was asking.
#
# DESIGN NOTES
#   * It IMPORTS the sync contract; it never carries its own table list. A copy
#     drifts, and a parity checker that has drifted reports green over the gap
#     it exists to find. Adding a table to PK_COLUMN extends coverage for free.
#   * UNKNOWN is a TYPED ABSENCE and never renders as 0 (see
#     specs/storage-retention-custody.md). An unreachable tier is not an empty
#     tier, and conflating them is how a dead destination shows a green light.
#   * One unreadable table never stops the others being checked -- the sync
#     contract itself taught that lesson when a missing table raised out of
#     pushAllDeltas and stopped ALL Pi->server sync.
#
# WHAT THIS DELIBERATELY DOES NOT DO
#   No "implausibly few rows" ratio. A table holding 3 rows that should hold 3
#   million is a real signal, but any threshold chosen today is a guess, and
#   this project has a long history of unvalidated constants hardening into
#   law. MISSING and EMPTY are unambiguous and would have caught the actual
#   incident. Ratios can come later, against real data.
#
# EXIT CODES
#   0  every table under contract exists and holds rows
#   1  at least one MISSING or EMPTY -- a definite defect
#   2  nothing definite, but at least one UNKNOWN -- undetermined, NOT success
#
# Author: Atlas (Architect) -- ARCH-038
# Creation Date: 2026-09-20
################################################################################

"""Cross-tier parity: does the destination for each synced table actually exist?"""

from __future__ import annotations

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

__all__ = [
    "EMPTY",
    "MISSING",
    "OK",
    "UNKNOWN",
    "UNUSED",
    "Result",
    "TableState",
    "checkTables",
    "exitCodeFor",
    "tablesUnderContract",
]

#: Verdicts. Strings rather than an enum so log lines and CI output read
#: directly without a lookup.
OK = "OK"
MISSING = "MISSING"
EMPTY = "EMPTY"
#: Destination is zero AND the producer has produced nothing. Not a defect --
#: a feature that has never run. Distinguishing this from EMPTY is the whole
#: reason the producer half exists; without it the check cried wolf on three
#: tables on its first real run.
UNUSED = "UNUSED"
UNKNOWN = "UNKNOWN"

#: A definite defect outranks an undetermined one: a MISSING table is a fact,
#: an UNKNOWN is the absence of one.
_EXIT_OK = 0
_EXIT_DEFECT = 1
_EXIT_UNDETERMINED = 2


@dataclass(frozen=True)
class TableState:
    """What a tier reports about one table.

    Attributes:
        exists: True / False, or None when it could not be determined.
        rows: Row count, or None when unknown. **Never 0 to mean "unreadable"**
            -- 0 is a real, different, and much more alarming answer.
    """

    exists: bool | None
    rows: int | None


@dataclass(frozen=True)
class Result:
    """One table's verdict."""

    table: str
    verdict: str
    rows: int | None
    #: Rows on the producer tier, when it was consulted. None means not asked
    #: or not determinable -- never 0, which is a real and different answer.
    producerRows: int | None = None


class Tier(Protocol):
    """A tier that can be asked about a table. The injection seam."""

    def inspect(self, table: str) -> TableState: ...


def tablesUnderContract() -> list[str]:
    """The tables the sync contract covers -- read from the contract itself.

    Returns:
        Sorted table names from :data:`src.pi.data.sync_log.IN_SCOPE_TABLES`.
    """
    # Run directly (not under pytest) the repo root is not on sys.path, so the
    # contract import fails. Put it there rather than duplicating the table
    # list, which is the one thing this module must never do.
    root = str(_repoRoot())
    if root not in sys.path:
        sys.path.insert(0, root)

    from src.pi.data.sync_log import IN_SCOPE_TABLES  # noqa: PLC0415

    return sorted(IN_SCOPE_TABLES)


def _verdictFor(
    state: TableState, producerState: TableState | None = None
) -> tuple[str, int | None]:
    """Classify one table from the destination and (optionally) the producer.

    Order matters: undetermined is decided before empty, and a MISSING
    destination outranks anything the producer says -- the contract names the
    table, so its absence is a defect regardless of whether anything has been
    written yet.

    🔴 A zero destination is only a DEFECT when the producer has rows. Zero on
    both tiers is an UNUSED feature, and calling that a defect is the bare
    threshold inside the normal operating range that this project has
    catalogued five times.
    """
    if state.exists is None:
        return UNKNOWN, None
    if not state.exists:
        return MISSING, None
    if state.rows is None:
        # It exists but we could not count it. Undetermined -- NOT empty, and
        # emphatically not OK.
        return UNKNOWN, None
    if state.rows == 0:
        if producerState is None or producerState.rows is None:
            # Genuinely ambiguous: this is either A-37 or an unused feature,
            # and the destination alone cannot tell which.
            return UNKNOWN, 0
        if producerState.rows > 0:
            return EMPTY, 0
        return UNUSED, 0
    return OK, state.rows


def checkTables(
    tables: list[str], tier: Tier, producer: Tier | None = None
) -> list[Result]:
    """Ask the tier about each table and classify the answers.

    A table whose inspection RAISES becomes UNKNOWN rather than aborting the
    run: one unreadable destination must not hide the state of the others.

    Args:
        tables: Table names to check.
        tier: The DESTINATION tier (the server).
        producer: Optional PRODUCER tier (the Pi). Without it a zero
            destination is reported UNKNOWN rather than guessed at.

    Returns:
        One :class:`Result` per input table, in input order.

    Raises:
        TypeError: A table name is not a string.
        ValueError: A table name is empty.
    """
    results: list[Result] = []
    for table in tables:
        if not isinstance(table, str):
            raise TypeError(f"table name must be a string, got {type(table).__name__}")
        if not table:
            raise ValueError("table name must not be empty")
        try:
            state = tier.inspect(table)
        except Exception:  # noqa: BLE001 -- one bad table must not mask the rest
            results.append(Result(table=table, verdict=UNKNOWN, rows=None))
            continue
        producerState: TableState | None = None
        if producer is not None:
            try:
                producerState = producer.inspect(table)
            except Exception:  # noqa: BLE001 -- an unreadable producer is not a defect
                producerState = None
        verdict, rows = _verdictFor(state, producerState)
        results.append(
            Result(
                table=table,
                verdict=verdict,
                rows=rows,
                producerRows=None if producerState is None else producerState.rows,
            )
        )
    return results


def exitCodeFor(results: list[Result]) -> int:
    """0 clean, 1 a definite defect, 2 undetermined.

    🔴 UNKNOWN never exits 0. A check that reports success because it could not
    reach the database is an inert guard -- present, syntactically correct, and
    enforcing nothing.
    """
    if any(r.verdict in (MISSING, EMPTY) for r in results):
        return _EXIT_DEFECT
    if any(r.verdict == UNKNOWN for r in results):
        return _EXIT_UNDETERMINED
    return _EXIT_OK


class ServerTier:
    """The production server, reached the way the rest of the fleet reaches it.

    Delegates to ``tools/pm/prod_db_query.sh`` rather than opening its own
    connection: a local ``mysql.exe`` fails over Tailscale, and a second access
    path is a second thing to keep working.
    """

    def __init__(self, repoRoot: Path | None = None) -> None:
        self._root = repoRoot or _repoRoot()
        self._script = self._root / "tools" / "pm" / "prod_db_query.sh"
        self._existing: set[str] | None = None
        self._counts: dict[str, int] = {}
        #: Why the last query failed, surfaced so an UNKNOWN says what went
        #: wrong instead of being a silent shrug.
        self.lastError: str | None = None

    def _run(self, sql: str) -> str | None:
        try:
            done = subprocess.run(  # noqa: S603
                [_findBash(), str(self._script), sql],
                capture_output=True,
                text=True,
                # US-597/TD-068: text mode without an explicit encoding decodes
                # the child's UTF-8 through the parent's locale codec.
                encoding="utf-8",
                # The query script resolves its config relative to the repo
                # root; run it from anywhere else and it cannot find the
                # credentials.
                cwd=str(self._root),
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.lastError = f"{type(exc).__name__}: {exc}"
            return None
        if done.returncode != 0:
            self.lastError = (
                f"exit {done.returncode}: {(done.stderr or done.stdout or '').strip()[:300]}"
            )
            return None
        return done.stdout

    def prime(self, tables: list[str]) -> None:
        """Two round trips for N tables, not N+1: existence, then one UNION."""
        listing = self._run(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = DATABASE();"
        )
        if listing is None:
            self._existing = None
            return
        self._existing = {
            line.strip().split("\t")[0] for line in listing.splitlines() if line.strip()
        }
        present = [t for t in tables if t in self._existing]
        if not present:
            return
        union = " UNION ALL ".join(
            f"SELECT '{t}' AS t, COUNT(*) AS n FROM `{t}`" for t in present
        )
        counts = self._run(union + ";")
        if counts is None:
            return
        for line in counts.splitlines():
            parts = line.strip().split("\t")
            if len(parts) == 2 and parts[1].isdigit():
                self._counts[parts[0]] = int(parts[1])

    def inspect(self, table: str) -> TableState:
        if self._existing is None:
            return TableState(exists=None, rows=None)
        if table not in self._existing:
            return TableState(exists=False, rows=None)
        return TableState(exists=True, rows=self._counts.get(table))


#: The producer tier. Fleet defaults, overridable on the CLI.
PI_HOST = "chi-eclipse-01"
PI_DB = "/home/mcornelison/Projects/Eclipse-01/data/obd.db"


class PiTier:
    """The PRODUCER tier -- the Pi's local SQLite, over SSH.

    Consulted so a zero destination can be told apart from a feature that has
    never produced anything. 🔴 It is NEVER required: an unreachable Pi leaves a
    zero destination as UNKNOWN, which is honest, rather than as a defect, which
    would cry wolf on every run and get the whole check ignored.
    """

    def __init__(self, host: str = PI_HOST, dbPath: str = PI_DB) -> None:
        self._host = host
        self._db = dbPath
        self._counts: dict[str, int] = {}
        self._reachable = False
        self.lastError: str | None = None

    def prime(self, tables: list[str]) -> None:
        """One SSH round trip for every table, not one per table.

        A per-table loop on the remote side rather than a UNION: a UNION over a
        table that does not exist fails the WHOLE query, which would turn one
        absent table into sixteen UNKNOWNs.
        """
        names = " ".join(f"'{t}'" for t in tables)
        script = (
            f"for t in {names}; do "
            f'n=$(sqlite3 "{self._db}" "SELECT COUNT(*) FROM \\"$t\\";" 2>/dev/null); '
            f'if [ -n "$n" ]; then echo "$t|$n"; else echo "$t|ABSENT"; fi; '
            f"done"
        )
        try:
            done = subprocess.run(  # noqa: S603
                [
                    "ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10",
                    self._host, script,
                ],
                capture_output=True,
                text=True,
                encoding="utf-8",  # US-597/TD-068
                timeout=90,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            self.lastError = f"{type(exc).__name__}: {exc}"
            return
        if done.returncode != 0:
            self.lastError = (
                f"exit {done.returncode}: {(done.stderr or '').strip()[:200]}"
            )
            return
        self._reachable = True
        for line in done.stdout.splitlines():
            name, _, count = line.strip().partition("|")
            if count.isdigit():
                self._counts[name] = int(count)

    def inspect(self, table: str) -> TableState:
        if not self._reachable:
            return TableState(exists=None, rows=None)
        if table not in self._counts:
            return TableState(exists=False, rows=None)
        return TableState(exists=True, rows=self._counts[table])


def _findBash() -> str:
    """Resolve a POSIX bash, preferring Git Bash on Windows.

    🔴 On Windows, a bare ``bash`` on PATH resolves to **WSL**, which on this
    bench reports *"Windows Subsystem for Linux has no installed
    distributions"* and exits 1. The fleet's shell scripts run under Git Bash.
    Resolving explicitly turns a confusing environment failure into a working
    call -- and the error text that found this is why ``lastError`` exists.
    """
    for candidate in (
        Path("C:/Program Files/Git/bin/bash.exe"),
        Path("C:/Program Files/Git/usr/bin/bash.exe"),
    ):
        if candidate.is_file():
            return str(candidate)
    return "bash"  # POSIX hosts, and any box where PATH bash is the right one


def _repoRoot() -> Path:
    """Walk up for pyproject.toml -- depth-independent, never parents[N]."""
    here = Path(__file__).resolve()
    for candidate in (here, *here.parents):
        if (candidate / "pyproject.toml").is_file():
            return candidate
    raise RuntimeError("repo root not found (no pyproject.toml above this file)")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--quiet", action="store_true", help="only print non-OK verdicts"
    )
    parser.add_argument(
        "--no-producer",
        action="store_true",
        help="skip the Pi; a zero destination then reports UNKNOWN, not a defect",
    )
    parser.add_argument("--pi-host", default=PI_HOST)
    parser.add_argument("--pi-db", default=PI_DB)
    args = parser.parse_args(argv)

    tables = tablesUnderContract()
    tier = ServerTier()
    tier.prime(tables)

    producer: PiTier | None = None
    if not args.no_producer:
        producer = PiTier(host=args.pi_host, dbPath=args.pi_db)
        producer.prime(tables)

    results = checkTables(tables, tier, producer=producer)

    for r in results:
        if args.quiet and r.verdict in (OK, UNUSED):
            continue
        rows = "-" if r.rows is None else f"{r.rows:,}"
        pi = "-" if r.producerRows is None else f"{r.producerRows:,}"
        print(f"{r.verdict:<8} {r.table:<24} server={rows:>13}  pi={pi:>13}")

    code = exitCodeFor(results)
    bad = [r.table for r in results if r.verdict in (MISSING, EMPTY)]
    unknown = [r.table for r in results if r.verdict == UNKNOWN]
    unused = [r.table for r in results if r.verdict == UNUSED]
    if bad:
        print(f"\nDEFECT: {len(bad)} table(s) missing or empty: {', '.join(bad)}")
    if unknown:
        print(f"UNDETERMINED: {len(unknown)} table(s): {', '.join(unknown)}")
        if tier.lastError:
            print(f"  server: {tier.lastError}")
        if producer is not None and producer.lastError:
            print(f"  producer: {producer.lastError}")
    if unused:
        print(f"UNUSED (not a defect): {len(unused)}: {', '.join(unused)}")
    if not bad and not unknown:
        print(f"\nAll {len(results)} tables under contract accounted for.")
    return code


if __name__ == "__main__":
    sys.exit(main())
