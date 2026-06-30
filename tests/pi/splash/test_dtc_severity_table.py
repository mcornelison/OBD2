################################################################################
# File Name: test_dtc_severity_table.py
# Purpose/Description: US-404 (F-111) tests for the static P1xxx severity-table
#   loader. Verifies the loader parses Spool's SSOT markdown
#   (offices/tuner/dsm-p1xxx-severity-table.md) into the {code -> enrichment}
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
    / "offices"
    / "tuner"
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
