################################################################################
# File Name: gap_analysis.py
# Purpose/Description: US-808-d -- account for the Pi-vs-server connection_log
#                      difference in an exported window, per event type, from
#                      the CSVs alone. Reproduces the US-808-a reconciliation and
#                      the US-808-b per-type table.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-24
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-24    | Rex (US-808-d) | Rewrite of the lost Sprint 93 analysis tool,
#               |                | specified by its surviving output.
# ================================================================================
################################################################################
"""Account for the connection_log difference between the tiers, per event type.

Input is an export directory written by :mod:`tools.connlog.export_window` (or
the preserved ``data/us808-connection-log-export/``): a ``manifest.json`` and
one CSV per tier. The tool reads; it writes nothing.

The CSVs are counted directly. The manifest's own ``perEventType`` and
``rowsReadBack`` are then checked against those counts, so a manifest that no
longer describes its files fails the run instead of being believed.

The reconciliation, as US-808 states it::

    Pi rows - server rows of the retry types - explicit keeps = the gap

where the explicit keeps are the server's rows of every non-retry type. The
gap must also equal the sum of the per-type differences; when it does not, the
run fails.

Usage::

    python -m tools.connlog.gap_analysis data/us808-connection-log-export
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tools.connlog.export_window import EVENT_TYPE_COLUMN, ID_COLUMN, MANIFEST_NAME

#: The server keeps the Pi's id as ``source_id`` (A-45); it is the join key.
SOURCE_ID_COLUMN = "source_id"

#: Manifest key for the reference figures the preserved export carried.
_REFERENCE_KEY = "referenceCounts2026_09_14"


@dataclass
class TierCounts:
    """One tier's export, counted from its CSV."""

    tier: str
    rows: int
    perEventType: Counter[str]
    ids: list[int]
    manifestEntry: dict[str, Any]


@dataclass
class GapAnalysis:
    """Everything the report prints, as numbers a test can compare."""

    pi: TierCounts
    server: TierCounts
    retryEventTypes: list[str]
    differences: dict[str, int]
    serverRetryRows: int
    explicitKeeps: dict[str, int]
    gap: int
    missingRuns: list[tuple[int, int]]
    serverOrphans: int
    reference: dict[str, int] | None
    problems: list[str] = field(default_factory=list)

    @property
    def explicitKeepsTotal(self) -> int:
        return sum(self.explicitKeeps.values())

    @property
    def missingIds(self) -> int:
        return sum(hi - lo + 1 for lo, hi in self.missingRuns)

    @property
    def largestRun(self) -> int:
        return max((hi - lo + 1 for lo, hi in self.missingRuns), default=0)


def _csvFileName(manifestPath: str) -> str:
    """The file name from a manifest path written on either OS."""
    return re.split(r"[\\/]", manifestPath)[-1]


def loadTier(exportDir: Path, entry: dict[str, Any]) -> TierCounts:
    """Count one tier's CSV: rows, rows per event type, and the Pi-side ids."""
    path = exportDir / _csvFileName(entry["path"])
    idColumn = SOURCE_ID_COLUMN if entry["tier"] == "server" else ID_COLUMN
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    return TierCounts(
        tier=entry["tier"],
        rows=len(rows),
        perEventType=Counter(r[EVENT_TYPE_COLUMN] for r in rows),
        ids=[int(r[idColumn]) for r in rows if idColumn in r],
        manifestEntry=entry,
    )


def contiguousRuns(ids: list[int]) -> list[tuple[int, int]]:
    """Collapse sorted-or-not ids into ``(first, last)`` runs of consecutive values."""
    runs: list[tuple[int, int]] = []
    for i in sorted(set(ids)):
        if runs and i == runs[-1][1] + 1:
            runs[-1] = (runs[-1][0], i)
        else:
            runs.append((i, i))
    return runs


def _manifestProblems(counts: TierCounts) -> list[str]:
    """Where the manifest no longer describes the file it sits beside."""
    entry, problems = counts.manifestEntry, []
    if entry.get("rowsReadBack") != counts.rows:
        problems.append(
            f"{counts.tier}: manifest rowsReadBack {entry.get('rowsReadBack')} "
            f"but the CSV holds {counts.rows}"
        )
    if entry.get("rowsReported") != entry.get("rowsReadBack"):
        problems.append(
            f"{counts.tier}: the export itself failed read-back "
            f"({entry.get('rowsReported')} reported, {entry.get('rowsReadBack')} read back)"
        )
    if dict(entry.get("perEventType", {})) != dict(counts.perEventType):
        problems.append(f"{counts.tier}: manifest perEventType differs from the CSV")
    return problems


def analyse(exportDir: Path) -> GapAnalysis:
    """Count both tiers' CSVs and account for the difference between them.

    Args:
        exportDir: A directory holding ``manifest.json`` and one CSV per tier.

    Returns:
        The analysis. ``problems`` is empty only when every cross-check held.
    """
    with open(exportDir / MANIFEST_NAME, encoding="utf-8") as fh:
        manifest = json.load(fh)
    tiers = {e["tier"]: loadTier(exportDir, e) for e in manifest["exports"]}
    pi, server = tiers["pi"], tiers["server"]
    retryTypes = list(manifest["retryEventTypes"])

    eventTypes = sorted(
        set(pi.perEventType) | set(server.perEventType),
        key=lambda t: (-(pi.perEventType[t] - server.perEventType[t]), t),
    )
    differences = {t: pi.perEventType[t] - server.perEventType[t] for t in eventTypes}
    serverRetryRows = sum(server.perEventType[t] for t in retryTypes)
    keeps = {t: server.perEventType[t] for t in eventTypes if t not in retryTypes}
    gap = pi.rows - serverRetryRows - sum(keeps.values())

    piIds, serverIds = set(pi.ids), set(server.ids)
    analysis = GapAnalysis(
        pi=pi,
        server=server,
        retryEventTypes=retryTypes,
        differences=differences,
        serverRetryRows=serverRetryRows,
        explicitKeeps=keeps,
        gap=gap,
        missingRuns=contiguousRuns(list(piIds - serverIds)),
        serverOrphans=len(serverIds - piIds),
        reference=manifest.get(_REFERENCE_KEY),
    )

    problems = _manifestProblems(pi) + _manifestProblems(server)
    if gap != sum(differences.values()):
        problems.append(
            f"reconciliation {gap:,} != sum of per-type differences "
            f"{sum(differences.values()):,}"
        )
    if serverIds and analysis.missingIds != gap:
        problems.append(f"{analysis.missingIds:,} Pi ids absent on the server, gap is {gap:,}")
    analysis.problems = problems
    return analysis


def _drift(live: int, reference: dict[str, int] | None, key: str) -> str:
    if not reference or key not in reference:
        return ""
    ref = reference[key]
    return f"(reference {ref:,} -- {'no drift' if ref == live else f'DRIFT {live - ref:+,}'})"


def render(a: GapAnalysis) -> str:
    """The report, in the shape of the preserved README and findings."""
    ref = a.reference
    keepParts = " + ".join(f"{n:,} {t}" for t, n in a.explicitKeeps.items())
    out = [
        "=== connection_log gap, per event type ===",
        "",
        f"  {'event_type':<20}{'pi':>10}{'server':>10}{'difference':>12}",
    ]
    for t, diff in a.differences.items():
        out.append(
            f"  {t:<20}{a.pi.perEventType[t]:>10,}{a.server.perEventType[t]:>10,}{diff:>12,}"
        )
    out += [
        f"  {'TOTAL':<20}{a.pi.rows:>10,}{a.server.rows:>10,}{a.pi.rows - a.server.rows:>12,}",
        "",
        "=== reconciliation ===",
        "",
        f"  {a.pi.rows:>8,}   Pi rows before the window end  "
        + _drift(a.pi.rows, ref, "piRowsBeforeWindowEnd"),
        f"  -{a.serverRetryRows:>7,}   server rows, the retry types ({', '.join(a.retryEventTypes)})  "
        + _drift(a.serverRetryRows, ref, "serverRetryRowsBeforeWindowEnd"),
        f"  -{a.explicitKeepsTotal:>7,}   explicit keeps ({keepParts})",
        "  --------",
        f"  {a.gap:>8,}   the gap  " + _drift(a.gap, ref, "unexplainedDifference"),
        "",
        f"  missing ids form {len(a.missingRuns)} contiguous run(s); largest {a.largestRun:,}",
        f"  server rows with no Pi counterpart: {a.serverOrphans:,}",
        "",
    ]
    if a.problems:
        out += [f"  PROBLEM: {p}" for p in a.problems]
    else:
        out.append("  every cross-check held")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Account for the connection_log gap per event type.")
    ap.add_argument("exportDir", type=Path, help="directory holding manifest.json and the CSVs")
    a = ap.parse_args(argv)
    analysis = analyse(a.exportDir)
    print(render(analysis))
    return 1 if analysis.problems else 0


if __name__ == "__main__":
    sys.exit(main())
