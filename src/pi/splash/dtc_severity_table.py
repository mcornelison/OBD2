################################################################################
# File Name: dtc_severity_table.py
# Purpose/Description: F-111 static P1xxx severity-table loader [US-404]. Parses
#   Spool's SSOT markdown (src/pi/resources/dsm-p1xxx-severity-table.md) into the
#   {code -> enrichment} map the `dtc` emitter merges into each captured code.
#   The Pi NEVER decides severity -- it loads Spool's classification verbatim
#   (severity tier, condition-dependent caveat, clear-eligibility, mfr short
#   description, Spool-validated suggested fix). python-obd's DTC_MAP returns an
#   empty string for every Mitsubishi P1xxx, so this curated table is the only
#   source of meaning for the DSM-specific codes the ECMLink ECU throws. The
#   condition-dependent caveat (R-1: P1103/04/05/P1300) is rendered as a warning
#   line and NEVER silently upgrades the tier (design-spec §4/§5.4).
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-404 P1xxx severity-table loader.
# ================================================================================
################################################################################

"""Loader for Spool's DSM P1xxx severity SSOT (F-111 / US-404).

The display feature is a pure consumer of the upstream classification. This
loader is the Pi-side seam that reads Spool's hand-maintained markdown table
and yields a machine-readable map; if the table changes, Spool edits the
markdown SSOT and the loader follows -- there is no second copy of the tiers
in code (Refusal Rule 2 / the "Pi never decides severity" cardinal rule).
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Severity tiers (mirror the `dtc` state `severity` enum, design-spec §8).
SEVERITY_STOP = "stop"
SEVERITY_WATCH = "watch"
SEVERITY_MINOR = "minor"
SEVERITY_NA = "na"
SEVERITY_UNKNOWN = "unknown"

# Provenance tags for the suggested-fix trust badge (design-spec §5.4).
FIX_PROVENANCE_SPOOL = "spool-validated"
FIX_PROVENANCE_NONE = "none"

__all__ = [
    "FIX_PROVENANCE_NONE",
    "FIX_PROVENANCE_SPOOL",
    "SEVERITY_MINOR",
    "SEVERITY_NA",
    "SEVERITY_STOP",
    "SEVERITY_UNKNOWN",
    "SEVERITY_WATCH",
    "loadP1xxxSeverityTable",
]


def _tierFromText(text: str) -> str:
    """Map the leading severity emoji in ``text`` to a tier string.

    The first (highest-priority) emoji present wins; this only inspects the
    *base* tier portion of a cell (the caller splits off any ``->`` caveat
    first), so a "watch -> stop if knock" cell resolves to ``watch``.
    """
    if "\U0001f534" in text:  # 🔴
        return SEVERITY_STOP
    if "\U0001f7e1" in text:  # 🟡
        return SEVERITY_WATCH
    if "\U0001f7e2" in text:  # 🟢
        return SEVERITY_MINOR
    return SEVERITY_UNKNOWN


def _parseTierCell(cell: str) -> tuple[str, str | None]:
    """Split a severity cell into (base tier, optional condition caveat).

    Spool encodes condition-dependent codes as ``🟡 WATCH -> 🔴 if overboost``:
    the base tier is everything before the ``->`` arrow, and the text after is
    the caveat. The caveat NEVER upgrades the tier (R-1) -- it is surfaced as a
    warning line only. A plain ``🟡 WATCH`` cell yields ``(watch, None)``.
    """
    clean = cell.replace("*", "").strip()
    if "→" in clean:  # '->' rendered as the Unicode rightwards arrow
        base, _, after = clean.partition("→")
        caveat = after.strip() or None
        return (_tierFromText(base), caveat)
    return (_tierFromText(clean), None)


def _stripCode(cell: str) -> str:
    """Extract a bare ``Pxxxx`` code from a markdown cell (strip ``**`` etc.)."""
    return cell.replace("*", "").strip()


def _splitRow(line: str) -> list[str]:
    """Split a markdown table row ``| a | b | c |`` into trimmed cell strings."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _isSeparatorRow(cells: list[str]) -> bool:
    """True for a markdown header underline row (``|---|:--:|`` etc.)."""
    joined = "".join(cells)
    return joined != "" and set(joined) <= set("-: ")


def loadP1xxxSeverityTable(path: str) -> dict[str, dict]:
    """Parse Spool's P1xxx severity SSOT into a ``{code -> enrichment}`` map.

    The markdown has two tables: the engine-relevant P1xxx (5 columns:
    code / description / severity / clearable / suggested-fix) and the
    auto-transmission P1xxx (3 columns: code / description / disposition),
    which are ``na`` on this manual car. Rows outside those two tables are
    ignored, so surrounding prose never pollutes the map.

    Args:
        path: Filesystem path to ``dsm-p1xxx-severity-table.md``.

    Returns:
        A map keyed by uppercase DTC code; each value carries
        ``severity`` / ``severityCaveat`` / ``short`` / ``long`` /
        ``suggestedFix`` / ``fixProvenance`` / ``clearEligible``. Returns an
        empty map (never raises) when the file is absent or unreadable, so a
        missing table degrades to "no enrichment" rather than crashing the
        emitter -- un-tabled codes fall through to ``unknown`` downstream.
    """
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        logger.warning(
            "P1xxx severity table unreadable at %s (%s) -- no enrichment", path, exc
        )
        return {}

    table: dict[str, dict] = {}
    mode: str | None = None  # 'engine' | 'na' | None (outside a known table)

    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            mode = None  # left the table -- prose / blank line
            continue

        cells = _splitRow(stripped)
        joined = " ".join(cells).lower()

        if "severity" in joined and "clearable" in joined:
            mode = "engine"
            continue
        if "disposition" in joined:
            mode = "na"
            continue
        if _isSeparatorRow(cells):
            continue

        if mode == "engine" and len(cells) >= 5:
            code = _stripCode(cells[0]).upper()
            if not code:
                continue
            severity, caveat = _parseTierCell(cells[2])
            short = cells[1].replace("*", "").strip()
            table[code] = {
                "severity": severity,
                "severityCaveat": caveat,
                "short": short,
                "long": short,
                "suggestedFix": cells[4].strip() or None,
                "fixProvenance": FIX_PROVENANCE_SPOOL,
                "clearEligible": cells[3].lower().startswith("yes"),
            }
        elif mode == "na" and len(cells) >= 3:
            code = _stripCode(cells[0]).upper()
            if not code:
                continue
            short = cells[1].replace("*", "").strip()
            table[code] = {
                "severity": SEVERITY_NA,
                "severityCaveat": None,
                "short": short,
                "long": short,
                "suggestedFix": None,
                "fixProvenance": FIX_PROVENANCE_NONE,
                "clearEligible": False,
            }

    return table
