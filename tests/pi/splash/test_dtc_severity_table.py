################################################################################
# File Name: test_dtc_severity_table.py
# Purpose/Description: US-404 (F-111) tests for the static P1xxx severity-table
#   loader. Verifies the loader parses Spool's SSOT markdown
#   (src/pi/resources/dsm-p1xxx-severity-table.md) into the {code -> enrichment}
#   map the dtc emitter merges -- engine P1xxx -> watch, condition-dependent
#   codes carry a severityCaveat (never auto-upgraded), auto-trans P1xxx -> na.
#   The Pi never decides severity; it loads Spool's classification verbatim.
# Author: Ralph Agent (Rex)
# Creation Date: 2026-06-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-06-30    | Ralph (Rex)  | Initial -- US-404 P1xxx severity-table loader.
# 2026-10-19    | Ralph (Rex)  | US-754-a -- Title + Sentence columns.
# ================================================================================
################################################################################

"""Tests for :mod:`src.pi.splash.dtc_severity_table` (US-404 Spool SSOT loader)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pi.splash.dtc_severity_table import (
    SEVERITY_NA,
    SEVERITY_WATCH,
    loadP1xxxSeverityTable,
)

# The Spool SSOT this loader exists to consume (repo-relative).
_SSOT_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "pi"
    / "resources"
    / "dsm-p1xxx-severity-table.md"
)


@pytest.fixture
def table() -> dict:
    """The parsed Spool SSOT table (the real file -- it IS the contract)."""
    return loadP1xxxSeverityTable(str(_SSOT_PATH))


def test_loadP1xxxSeverityTable_engineCode_classifiedWatchNonClearable(table):
    """
    Given: Spool's SSOT table
    When: a plain engine P1xxx (P1400 MDP sensor) is looked up
    Then: it is WATCH, not clearable, no caveat, with the Spool fix text
    """
    entry = table["P1400"]

    assert entry["severity"] == SEVERITY_WATCH
    assert entry["clearEligible"] is False
    assert entry["severityCaveat"] is None
    assert entry["fixProvenance"] == "spool-validated"
    assert entry["suggestedFix"]  # non-empty Spool fix text
    assert "MDP" in entry["short"] or "Manifold" in entry["short"]


def test_loadP1xxxSeverityTable_conditionDependent_carriesCaveatNotUpgraded(table):
    """
    Given: Spool's SSOT table
    When: a condition-dependent code (P1300 ignition timing) is looked up
    Then: base tier stays WATCH and a severityCaveat is present (R-1 -- the
          caveat warns; it never silently upgrades the tier to stop)
    """
    entry = table["P1300"]

    assert entry["severity"] == SEVERITY_WATCH  # NOT auto-upgraded to stop
    assert entry["severityCaveat"] is not None
    assert "knock" in entry["severityCaveat"].lower()
    assert entry["clearEligible"] is False


def test_loadP1xxxSeverityTable_autoTransCode_classifiedNa(table):
    """
    Given: Spool's SSOT table
    When: an auto-trans-only P1xxx (P1750) is looked up
    Then: severity is `na` (quiet disposition -- this manual car can't set it)
    """
    entry = table["P1750"]

    assert entry["severity"] == SEVERITY_NA
    assert entry["clearEligible"] is False
    assert entry["suggestedFix"] is None  # no fix for a code that can't set


def test_loadP1xxxSeverityTable_coversAllSpoolEngineAndAutoTransCodes(table):
    """
    Given: Spool's SSOT table
    When: parsed
    Then: all 6 engine P1xxx + all 5 auto-trans P1xxx are present (no row lost)
    """
    engine = {"P1103", "P1104", "P1105", "P1300", "P1400", "P1500", "P1600"}
    autoTrans = {"P1715", "P1750", "P1751", "P1791", "P1795"}

    assert engine <= set(table)
    assert autoTrans <= set(table)
    # Every auto-trans code is `na`; none of the engine codes are.
    assert all(table[c]["severity"] == SEVERITY_NA for c in autoTrans)
    assert all(table[c]["severity"] != SEVERITY_NA for c in engine)


def test_loadP1xxxSeverityTable_allFourConditionDependentCarryCaveat(table):
    """
    Given: Spool's SSOT table
    When: the 4 condition-dependent codes are looked up
    Then: each carries a severityCaveat (P1103/04/05 boost/lean, P1300 knock)
    """
    for code in ("P1103", "P1104", "P1105", "P1300"):
        assert table[code]["severityCaveat"] is not None, code


def test_loadP1xxxSeverityTable_missingFile_returnsEmptyMap(tmp_path):
    """
    Given: a path that does not exist
    When: the loader runs
    Then: it returns an empty map (honest-instrument -- absence is not a crash;
          un-tabled codes fall through to severity `unknown` downstream)
    """
    missing = tmp_path / "nope.md"

    assert loadP1xxxSeverityTable(str(missing)) == {}


# US-754-a: Spool's title + sentence per engine code (Spool 2026-10-19 S2, verbatim).
_ENGINE_WORDS = {
    "P1103": ("WASTEGATE (P1103)", "No full throttle. Get it diagnosed."),
    "P1104": ("BOOST SOLENOID (P1104)", "No full throttle. Get it diagnosed."),
    "P1105": ("FUEL PRESSURE (P1105)", "No full throttle. Get it diagnosed."),
    "P1300": ("TIMING CIRCUIT (P1300)", "No full throttle. Get it diagnosed."),
    "P1400": ("EGR SENSOR (P1400)", "Drive gently. Get it diagnosed."),
    "P1500": ("CHARGING SIGNAL (P1500)", "Watch battery voltage. Get it checked."),
    "P1600": ("ECU LINK (P1600)", "Drive gently. Get it diagnosed."),
}


def test_loadP1xxxSeverityTable_engineCodes_carrySpoolTitleAndSentenceVerbatim(table):
    """
    Given: Spool's SSOT table with the Title + Sentence columns
    When: each of the 7 engine P1xxx is looked up
    Then: title and sentence are Spool's exact words, and the tier is unchanged
    """
    for code, (title, sentence) in _ENGINE_WORDS.items():
        assert table[code]["title"] == title, code
        assert table[code]["sentence"] == sentence, code
        assert table[code]["severity"] == SEVERITY_WATCH, code


def test_loadP1xxxSeverityTable_autoTransCodes_titleAndSentenceNone(table):
    """
    Given: Spool's SSOT table, whose auto-trans rows leave Title/Sentence empty
    When: each `na` code is looked up
    Then: title and sentence are None (an empty cell is never an empty string)
    """
    for code in ("P1715", "P1750", "P1751", "P1791", "P1795"):
        assert table[code]["title"] is None, code
        assert table[code]["sentence"] is None, code


def test_loadP1xxxSeverityTable_p1103FixNamesTheTurboNotTd04(table):
    """
    Given: the car runs a Garrett TB2566, not a TD04 (Spool 2026-10-19 S2)
    When: P1103's suggested fix is read
    Then: it says 'the turbo' and no longer names the TD04
    """
    fix = table["P1103"]["suggestedFix"]

    assert "the turbo" in fix
    assert "TD04" not in fix


def test_loadP1xxxSeverityTable_columnsMappedByHeaderNameNotPosition(tmp_path):
    """
    Given: an engine table whose Title/Sentence headers are mixed-case and
           whose Sentence column comes BEFORE Title
    When: the loader runs
    Then: each value lands under its header's key, not its position
    """
    path = tmp_path / "table.md"
    path.write_text(
        "| Code | Description (mfr) | Severity | Clearable | Suggested fix | SENTENCE | title |\n"
        "|---|---|---|---|---|---|---|\n"
        "| P1400 | MDP Sensor | \U0001f7e1 WATCH | No | Check it. | Drive gently. | EGR SENSOR |\n",
        encoding="utf-8",
    )

    entry = loadP1xxxSeverityTable(str(path))["P1400"]

    assert entry["title"] == "EGR SENSOR"
    assert entry["sentence"] == "Drive gently."


def test_loadP1xxxSeverityTable_tableWithoutTitleSentenceHeaders_stillLoads(tmp_path):
    """
    Given: both tables in the pre-US-754-a shape (no Title/Sentence columns)
    When: the loader runs
    Then: every row still loads, with title and sentence both None
    """
    path = tmp_path / "table.md"
    path.write_text(
        "| Code | Description (mfr) | Severity | Clearable | Suggested fix (Spool) |\n"
        "|---|---|---|---|---|\n"
        "| P1400 | MDP Sensor | \U0001f7e1 WATCH | No | Check it. |\n"
        "\n"
        "| Code | Description (mfr) | Disposition |\n"
        "|---|---|---|\n"
        "| P1750 | Solenoid Assembly (A/T) | N/A -- auto-trans only |\n",
        encoding="utf-8",
    )

    table = loadP1xxxSeverityTable(str(path))

    assert table["P1400"]["severity"] == SEVERITY_WATCH
    assert table["P1400"]["suggestedFix"] == "Check it."
    assert table["P1400"]["title"] is None
    assert table["P1400"]["sentence"] is None
    assert table["P1750"]["severity"] == SEVERITY_NA
    assert table["P1750"]["title"] is None
    assert table["P1750"]["sentence"] is None
