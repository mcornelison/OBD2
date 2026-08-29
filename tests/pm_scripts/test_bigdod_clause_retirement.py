################################################################################
# File Name: test_bigdod_clause_retirement.py
# Purpose/Description: TDD coverage for the US-619 bigDefinitionOfDone clause
#     RETIRE/SUPERSEDE mechanism in tools/pm/chain_validate_aggregate.py --
#     loadRetirements() + annotateRetirements(), the tools/pm/bigdod_retirements.json
#     ledger, and the --retirements / --strict CLI surface.
#
#     The founding case: the V0.29.29 clause "(output is the panel-native 480x320
#     ...)  [from US-552]" is unsatisfiable by hardware per BL-034 (the OSOYOO
#     HDMI35 is a scaler panel advertising no 480x320 mode; 720p IS the shipping
#     configuration). Any sweep reaching it can only fail the chain or write
#     evidence for something that did not happen.
#
#     The load-bearing control is test_substringWouldRetireBothClauses: the
#     V0.29.15 "[from US-482]" sibling ALSO contains "480x320" and describes the
#     shipping arrangement EXACTLY. Retiring it by association is forbidden, and
#     is what a substring rule would do.
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-28    | Rex (US-619) | Initial -- retire/supersede route for a chain
#               |              | bigDoD clause invalidated by a LATER hardware
#               |              | finding. Would FAIL pre-fix: loadRetirements /
#               |              | annotateRetirements do not exist and the ledger
#               |              | is not shipped (AttributeError on module load).
# ================================================================================
################################################################################

"""TDD tests for US-619: retiring a bigDefinitionOfDone clause.

The mechanism is ADDITIVE by design. Archive snapshots are testimony and are
never edited -- a clause is retired by adding a record to the ledger, which is
overlaid at read time. So these tests assert two things that pull in opposite
directions and must BOTH hold:

  * the retired clause is MARKED (with its superseding authority cited), and
  * the retired clause is STILL PRESENT -- retirement is not deletion.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "tools" / "pm" / "chain_validate_aggregate.py"
_SCRIPT_MODULE = "tools.pm.chain_validate_aggregate"
_SHIPPED_LEDGER = _PROJECT_ROOT / "tools" / "pm" / "bigdod_retirements.json"

# The two clauses at the heart of AC-6. Substrings only -- the tests resolve the
# VERBATIM text from the live chain, because hand-typing it is the exact mistake
# that produces an inert retirement (the real text carries U+2192, not '->').
_RETIRED_MARKER = "output is the panel-native 480x320"
_SIBLING_MARKER = "480x320 UI scales up centered"


def _loadTool():  # noqa: ANN202 -- test helper
    """Load tools/pm/chain_validate_aggregate.py as a module.

    The tool does `from tools.pm._paths import SHARE_ROOT`, which resolves from
    $FLEET_SHARE with no fallback -- so merely IMPORTING it is a configuration
    error when the share is unset. Point it at a throwaway dir so this file is
    runnable without the share instead of ERRORING during collection (I-us553).
    """
    if not os.environ.get("FLEET_SHARE"):
        os.environ["FLEET_SHARE"] = tempfile.mkdtemp(prefix="us619_shareless_")

    spec = importlib.util.spec_from_file_location("_us619_chain_aggregate", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, (
        f"chain_validate_aggregate.py not found at {_SCRIPT_PATH}"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _writeSprint(
    directory: Path,
    currentVersion: str,
    validatedAt: str | None = None,
    bigDoD: list[str] | None = None,
) -> Path:
    """Write a minimal sprint.json carrying the given bigDoD clauses."""
    payload = {
        "sprint": f"Synthetic {currentVersion}",
        "stories": [],
        "validation": {
            "bigDefinitionOfDone": bigDoD if bigDoD is not None else [f"Clause {currentVersion}"],
            "validatesFeatures": [],
            "currentVersion": currentVersion,
            "validatedAt": validatedAt,
            "validatedBy": "test" if validatedAt else None,
        },
    }
    path = directory / f"sprint.{currentVersion}.json"
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _writeLedger(path: Path, records: list[dict]) -> Path:
    """Write a retirement ledger containing the given records."""
    path.write_text(
        json.dumps({"schemaVersion": "1.0.0", "retirements": records}, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return path


def _record(currentVersion: str, clause: str, **overrides: object) -> dict:
    """Build a well-formed retirement record."""
    record = {
        "currentVersion": currentVersion,
        "clause": clause,
        "retiredAt": "2026-08-28",
        "retiredBy": "Atlas(Architect) BL-034 ruling R1, CIO-ratified 2026-08-27",
        "authority": "offices/pm/archive/intake-records/blockers/BL-034-....md",
        "reason": "unsatisfiable by hardware",
    }
    record.update(overrides)
    return record


def _realChain():  # noqa: ANN202 -- test helper
    """Aggregate the REAL V0.29 chain, or None when the share is unavailable."""
    tool = _loadTool()
    try:
        paths = tool.discoverChainPaths("V0.29")
    except OSError:
        return None
    result = tool.aggregateChain(paths, "V0.29")
    if not any(s["currentVersion"] == "V0.29.29" for s in result["sprintsInChain"]):
        return None
    return tool, result


_realChainOrNone = _realChain()
_needsShare = pytest.mark.skipif(
    _realChainOrNone is None,
    reason="the real V0.29 chain archives are not reachable (share not mounted)",
)


# ================================================================================
# 1. The founding case, measured against the REAL shipped ledger + real chain
# ================================================================================


class TestTheShippedLedgerRetiresTheUnsatisfiableClause:
    """AC-5 / VC-1: apply the route to the US-552 clause, citing BL-034."""

    @_needsShare
    def test_us552Clause_isMarkedRetiredWithItsAuthorityCited(self) -> None:
        """
        Given: the real V0.29 chain and the shipped retirement ledger
        When: the aggregate is annotated
        Then: the V0.29.29/US-552 clause is retired and names BL-034

        VC-1. A retirement with no cited authority is the unsourced claim this
        mechanism exists to prevent, so the authority is asserted, not just the
        boolean.
        """
        tool, result = _realChainOrNone
        annotated = tool.annotateRetirements(result, tool.loadRetirements())

        target = [
            e for e in annotated["aggregateBigDoD"]
            if e["currentVersion"] == "V0.29.29" and _RETIRED_MARKER in e["clause"]
        ]
        assert len(target) == 1, (
            f"expected exactly one V0.29.29 clause containing {_RETIRED_MARKER!r}, "
            f"found {len(target)}"
        )
        entry = target[0]

        assert entry["retired"] is True, (
            "the US-552 clause is unsatisfiable by hardware (BL-034: the OSOYOO "
            "HDMI35 is a scaler advertising no 480x320 mode) and must read as "
            "retired. Unretired, any sweep hitting it can only fail the chain or "
            "fabricate evidence."
        )
        assert "BL-034" in entry["retiredBy"] + entry["authority"], (
            "the retirement must cite BL-034 as its superseding authority"
        )
        assert entry["authority"].endswith(".md"), "authority must point at a document"

    @_needsShare
    def test_us482Sibling_isNotRetiredByAssociation(self) -> None:
        """
        Given: the sibling clause that also mentions 480x320
        When: the aggregate is annotated
        Then: it is NOT retired

        AC-6, called out specifically by Atlas. "[V0.29.15] 480x320 UI scales up
        centered on the real 1080p-output Pi [from US-482]" describes the
        SHIPPING arrangement exactly and is correct. This is the test that fails
        if anyone relaxes matching to a substring.
        """
        tool, result = _realChainOrNone
        annotated = tool.annotateRetirements(result, tool.loadRetirements())

        sibling = [
            e for e in annotated["aggregateBigDoD"]
            if e["currentVersion"] == "V0.29.15" and _SIBLING_MARKER in e["clause"]
        ]
        assert len(sibling) == 1, "the US-482 sibling clause is missing from the chain"
        assert sibling[0]["retired"] is False, (
            "the US-482 clause describes the shipping arrangement EXACTLY and must "
            "survive untouched. It shares the string '480x320' with the retired "
            "US-552 clause, so a substring match retires it by association -- "
            "which is precisely what US-619 AC-6 forbids."
        )

    @_needsShare
    def test_shippedLedger_retiresExactlyOneClause_andIsNotStale(self) -> None:
        """
        Given: the shipped ledger against the real chain
        When: the aggregate is annotated
        Then: exactly one clause is retired and nothing is stale

        A stale entry retires nothing while reporting that it does -- the inert
        guard. Pinning the COUNT is what catches a ledger that silently grows a
        second, over-broad record.
        """
        tool, result = _realChainOrNone
        annotated = tool.annotateRetirements(result, tool.loadRetirements())

        assert len(annotated["retiredBigDoD"]) == 1, (
            f"expected exactly 1 retired clause, got {len(annotated['retiredBigDoD'])}: "
            f"{[e['clause'][:60] for e in annotated['retiredBigDoD']]}"
        )
        assert annotated["staleRetirements"] == [], (
            "the shipped ledger no longer matches the chain it retires from. "
            "Re-copy the clause verbatim from the aggregate."
        )

    @_needsShare
    def test_retiredClause_isStillPresentInTheAggregate(self) -> None:
        """
        Given: a retired clause
        When: the aggregate is read
        Then: the clause is still listed

        Retirement is not deletion. Dropping the clause would erase the record of
        a claim the project once made; the reader must see BOTH the claim and the
        authority that withdrew it.
        """
        tool, result = _realChainOrNone
        before = len(result["aggregateBigDoD"])
        annotated = tool.annotateRetirements(result, tool.loadRetirements())

        assert len(annotated["aggregateBigDoD"]) == before
        assert any(
            _RETIRED_MARKER in e["clause"] for e in annotated["aggregateBigDoD"]
        ), "the retired clause was removed from the aggregate instead of marked"


# ================================================================================
# 2. Guard the guard -- prove the substring hazard is REAL
# ================================================================================


class TestTheSubstringHazardIsReal:
    """Without this, "exact matching" is an untested claim about a risk."""

    @_needsShare
    def test_substringWouldRetireBothClauses_whichIsWhyMatchingIsExact(self) -> None:
        """
        Given: the two 480x320 clauses in the real chain
        When: they are compared by substring and by exact text
        Then: substring hits both; exact text separates them

        The justification for exact matching, measured rather than asserted. If
        this ever fails, the two clauses have diverged and the exactness rule may
        be reconsidered on evidence -- but not before.
        """
        _tool, result = _realChainOrNone
        clauses = [e["clause"] for e in result["aggregateBigDoD"]]

        retired = [c for c in clauses if _RETIRED_MARKER in c]
        sibling = [c for c in clauses if _SIBLING_MARKER in c]
        assert len(retired) == 1 and len(sibling) == 1

        both = [c for c in clauses if "480x320" in c]
        assert len(both) >= 2, (
            "a substring rule on '480x320' matches more than the clause being "
            "retired -- this is the hazard exact matching exists to avoid"
        )
        assert retired[0] != sibling[0], "exact clause text must separate the two"


# ================================================================================
# 3. Mechanism semantics, on synthetic chains
# ================================================================================


class TestRetirementSemantics:
    """The reusable route, independent of the founding case."""

    def test_matchingClause_isMarkedAndCarriesTheAuthority(self, tmp_path: Path) -> None:
        """
        Given: a ledger record matching a clause exactly
        When: the aggregate is annotated
        Then: the clause is marked retired and carries the record's fields
        """
        tool = _loadTool()
        paths = [_writeSprint(tmp_path, "V0.30.1", None, ["clause A", "clause B"])]
        result = tool.aggregateChain(paths, "V0.30")

        annotated = tool.annotateRetirements(result, [_record("V0.30.1", "clause A")])

        byClause = {e["clause"]: e for e in annotated["aggregateBigDoD"]}
        assert byClause["clause A"]["retired"] is True
        assert byClause["clause A"]["authority"].startswith("offices/pm/")
        assert byClause["clause A"]["retiredAt"] == "2026-08-28"
        assert byClause["clause B"]["retired"] is False

    def test_clauseTextDrift_isReportedAsStaleNotSilentlyIgnored(self, tmp_path: Path) -> None:
        """
        Given: a ledger record whose clause text no longer matches the chain
        When: the aggregate is annotated
        Then: it is reported in staleRetirements

        The inert-guard defect: a retirement that retires nothing while the
        ledger reads as though the clause is handled.
        """
        tool = _loadTool()
        paths = [_writeSprint(tmp_path, "V0.30.1", None, ["the clause as it now reads"])]
        result = tool.aggregateChain(paths, "V0.30")

        annotated = tool.annotateRetirements(
            result, [_record("V0.30.1", "the clause as it USED to read")]
        )

        assert len(annotated["staleRetirements"]) == 1
        assert annotated["retiredBigDoD"] == []
        assert "matches nothing" in annotated["staleRetirements"][0]["why"]

    def test_recordForVersionOutsideTheChain_isSilentNotStale(self, tmp_path: Path) -> None:
        """
        Given: a ledger record for a sprint that is not in the aggregated chain
        When: a DIFFERENT chain is aggregated
        Then: nothing is retired and nothing is reported stale

        Not-applicable is not the same as stale. Without this distinction the
        shipped V0.29.29 record would report stale on every V0.27 aggregate and
        the signal would be worthless.
        """
        tool = _loadTool()
        paths = [_writeSprint(tmp_path, "V0.30.1", None, ["clause A"])]
        result = tool.aggregateChain(paths, "V0.30")

        annotated = tool.annotateRetirements(result, [_record("V0.29.29", "some other clause")])

        assert annotated["staleRetirements"] == []
        assert annotated["retiredBigDoD"] == []

    def test_retirement_doesNotChangeChainStatus(self, tmp_path: Path) -> None:
        """
        Given: a chain whose tip is unvalidated, with a retired clause in it
        When: the aggregate is annotated
        Then: chainStatus is still INCOMPLETE

        US-618 protection. Retirement annotates the clause LIST; the gate stays
        chain-tip-only (CIO 2026-05-23). Anyone who wires retirement into
        chainStatus has re-invented the all-sprints gate US-618 removed.
        """
        tool = _loadTool()
        paths = [
            _writeSprint(tmp_path, "V0.30.1", "2026-08-01T00:00:00Z", ["clause A"]),
            _writeSprint(tmp_path, "V0.30.2", None, ["clause B"]),
        ]
        result = tool.aggregateChain(paths, "V0.30")
        assert result["chainStatus"] == "INCOMPLETE"

        annotated = tool.annotateRetirements(
            result, [_record("V0.30.2", "clause B")]
        )

        assert annotated["chainStatus"] == "INCOMPLETE", (
            "retiring the tip's only outstanding clause must NOT flip the gate -- "
            "chainStatus reads validatedAt on the chain tip and nothing else"
        )

    def test_sameClauseTextDifferentSprint_isNotRetired(self, tmp_path: Path) -> None:
        """
        Given: two sprints carrying identical clause text, one retired
        When: the aggregate is annotated
        Then: only the named sprint's copy is retired

        The key is the (currentVersion, clause) PAIR. Clause text repeats across
        sprints in this project, so keying on text alone would retire history.
        """
        tool = _loadTool()
        paths = [
            _writeSprint(tmp_path, "V0.30.1", None, ["a shared clause"]),
            _writeSprint(tmp_path, "V0.30.2", None, ["a shared clause"]),
        ]
        result = tool.aggregateChain(paths, "V0.30")

        annotated = tool.annotateRetirements(result, [_record("V0.30.1", "a shared clause")])

        retiredVersions = [e["currentVersion"] for e in annotated["retiredBigDoD"]]
        assert retiredVersions == ["V0.30.1"]

    def test_emptyLedger_marksEveryClauseNotRetired(self, tmp_path: Path) -> None:
        """
        Given: no retirements at all
        When: the aggregate is annotated
        Then: every clause carries retired=False and nothing is stale

        The quiet case. A mechanism that only ever behaves correctly when it has
        something to do is not a mechanism.
        """
        tool = _loadTool()
        paths = [_writeSprint(tmp_path, "V0.30.1", None, ["clause A", "clause B"])]
        result = tool.aggregateChain(paths, "V0.30")

        annotated = tool.annotateRetirements(result, [])

        assert all(e["retired"] is False for e in annotated["aggregateBigDoD"])
        assert annotated["retiredBigDoD"] == []
        assert annotated["staleRetirements"] == []


# ================================================================================
# 4. Ledger integrity -- a record with no authority is not a retirement
# ================================================================================


class TestLedgerIntegrity:
    """The ledger is a claim about the physical world; it must cite a source."""

    @pytest.mark.parametrize("missing", ["currentVersion", "clause", "retiredBy", "authority"])
    def test_recordMissingARequiredField_raises(self, tmp_path: Path, missing: str) -> None:
        """
        Given: a retirement record with a required field absent
        When: the ledger is loaded
        Then: ValueError names the missing field

        'authority' is the load-bearing one: an uncited retirement withdraws a
        clause on nobody's say-so, which is the same defect class as a fixture
        asserting an unmeasured fact.
        """
        tool = _loadTool()
        record = _record("V0.30.1", "clause A")
        del record[missing]
        ledger = _writeLedger(tmp_path / "ledger.json", [record])

        with pytest.raises(ValueError, match=missing):
            tool.loadRetirements(ledger)

    def test_explicitLedgerPathThatDoesNotExist_raises(self, tmp_path: Path) -> None:
        """
        Given: an explicit --retirements path that does not exist
        When: the ledger is loaded
        Then: FileNotFoundError

        A typo must not degrade into "no retirements". Silently un-retiring every
        clause in the ledger is exactly the failure the mechanism must not have.
        """
        tool = _loadTool()
        with pytest.raises(FileNotFoundError):
            tool.loadRetirements(tmp_path / "nope.json")

    def test_absentDefaultLedger_isEmptyNotAnError(self, tmp_path: Path, monkeypatch) -> None:  # noqa: ANN001
        """
        Given: no default ledger on disk
        When: the ledger is loaded with no explicit path
        Then: it returns []

        A repo that has retired nothing yet is a valid state -- the difference
        from the test above is that nobody ASKED for a specific file.
        """
        tool = _loadTool()
        monkeypatch.setattr(tool, "DEFAULT_RETIREMENTS_PATH", tmp_path / "absent.json")
        assert tool.loadRetirements() == []

    def test_malformedJson_raises(self, tmp_path: Path) -> None:
        """
        Given: a ledger that is not valid JSON
        When: it is loaded
        Then: ValueError
        """
        tool = _loadTool()
        bad = tmp_path / "bad.json"
        bad.write_text("{not json", encoding="utf-8")
        with pytest.raises(ValueError):
            tool.loadRetirements(bad)

    def test_ledgerWithoutRetirementsList_raises(self, tmp_path: Path) -> None:
        """
        Given: a JSON ledger with no 'retirements' key
        When: it is loaded
        Then: ValueError
        """
        tool = _loadTool()
        bad = tmp_path / "bad.json"
        bad.write_text(json.dumps({"schemaVersion": "1.0.0"}), encoding="utf-8")
        with pytest.raises(ValueError, match="retirements"):
            tool.loadRetirements(bad)

    def test_shippedLedgerIsWellFormed(self) -> None:
        """
        Given: the ledger that actually ships
        When: it is loaded
        Then: it validates, and every record cites an authority

        Runs without the share -- the ledger is a repo file.
        """
        tool = _loadTool()
        records = tool.loadRetirements(_SHIPPED_LEDGER)
        assert records, "the shipped ledger retires nothing -- US-619 retires US-552's clause"
        for record in records:
            assert record["authority"].endswith(".md")
            assert record["reason"].strip()


# ================================================================================
# 5. CLI surface -- what the sweep operator actually sees (VC-2)
# ================================================================================


class TestCliSurface:
    """VC-2: the retire route must be VISIBLE to whoever runs the sweep."""

    def _run(self, tmp_path: Path, *extra: str) -> subprocess.CompletedProcess:
        paths = [
            _writeSprint(tmp_path, "V0.30.1", None, ["clause A", "clause B"]),
            _writeSprint(tmp_path, "V0.30.2", "2026-08-28T00:00:00Z", ["clause C"]),
        ]
        return subprocess.run(
            [sys.executable, "-m", _SCRIPT_MODULE, "--chain", "V0.30",
             "--paths", *[str(p) for p in paths], *extra],
            capture_output=True, text=True, cwd=_PROJECT_ROOT, encoding="utf-8",
        )

    def test_humanReport_showsRetiredMarkerAndAuthority(self, tmp_path: Path) -> None:
        """
        Given: a retired clause
        When: the human report is printed
        Then: it is marked RETIRED, cites its authority, and says not to discharge it

        The whole point of VC-2. An operator who cannot see the retirement is
        still forced to choose between failing the chain and fabricating.
        """
        ledger = _writeLedger(tmp_path / "ledger.json", [_record("V0.30.1", "clause A")])
        result = self._run(tmp_path, "--retirements", str(ledger))

        assert result.returncode == 0, result.stderr
        assert "[RETIRED]" in result.stdout
        assert "BL-034" in result.stdout
        assert "do NOT attempt to discharge this clause" in result.stdout
        assert "1 RETIRED" in result.stdout

    def test_jsonOutput_carriesRetiredFlagAndAuthority(self, tmp_path: Path) -> None:
        """
        Given: a retired clause
        When: --json is used
        Then: the entry carries retired=true plus the citation fields
        """
        ledger = _writeLedger(tmp_path / "ledger.json", [_record("V0.30.1", "clause A")])
        result = self._run(tmp_path, "--json", "--retirements", str(ledger))

        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        retired = payload["retiredBigDoD"]
        assert len(retired) == 1
        assert retired[0]["retired"] is True
        assert "BL-034" in retired[0]["retiredBy"]

    def test_strict_staleLedger_exitsOne(self, tmp_path: Path) -> None:
        """
        Given: a stale ledger entry and an otherwise READY chain
        When: --strict runs
        Then: exit 1, and the message distinguishes this from a gate failure

        --strict is the pre-flight for an operation that rewrites git history.
        Running it against a ledger that no longer describes the chain is a stop.
        """
        ledger = _writeLedger(tmp_path / "ledger.json", [_record("V0.30.1", "clause GONE")])
        result = self._run(tmp_path, "--strict", "--retirements", str(ledger))

        assert result.returncode == 1
        assert "stale retirement" in result.stderr
        assert "STALE RETIREMENTS" in result.stdout

    def test_strict_cleanLedger_exitsZero(self, tmp_path: Path) -> None:
        """
        Given: a valid ledger and a READY chain
        When: --strict runs
        Then: exit 0

        The control for the test above -- without it, "exit 1" is equally
        consistent with a gate that always fails once a ledger is supplied.
        """
        ledger = _writeLedger(tmp_path / "ledger.json", [_record("V0.30.1", "clause A")])
        result = self._run(tmp_path, "--strict", "--retirements", str(ledger))

        assert result.returncode == 0, f"{result.stdout}\n{result.stderr}"

    def test_badLedgerPath_exitsTwo(self, tmp_path: Path) -> None:
        """
        Given: a --retirements path that does not exist
        When: the CLI runs
        Then: exit 2 (file error), not a silent success
        """
        result = self._run(tmp_path, "--retirements", str(tmp_path / "nope.json"))

        assert result.returncode == 2
        assert "retirement ledger not found" in result.stderr

    def test_noRetirements_reportIsUnchangedInShape(self, tmp_path: Path) -> None:
        """
        Given: an empty ledger
        When: the human report is printed
        Then: no RETIRED marker and no stale section appear

        Guards against the annotation layer leaking noise into every report the
        PM reads, which is how a mechanism gets switched off.
        """
        ledger = _writeLedger(tmp_path / "ledger.json", [])
        result = self._run(tmp_path, "--retirements", str(ledger))

        assert result.returncode == 0, result.stderr
        assert "[RETIRED]" not in result.stdout
        assert "STALE RETIREMENTS" not in result.stdout
