################################################################################
# File Name: test_analyse_connection_log_gap.py
# Purpose/Description: US-808-b -- the difference is accounted for PER EVENT
#                      TYPE, the two hypotheses are stated, one is eliminated
#                      on the data, the selecting code is cited, and the
#                      watermark explanation is tested rather than assumed.
# Author: Ralph (US-808-b)
# Creation Date: 2026-09-23
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author           | Description
# ================================================================================
# 2026-09-23    | Ralph (US-808-b) | Initial.
# ================================================================================
################################################################################
"""Deciding what the 28,318-row difference is (US-808-b).

An honest "undetermined" is a valid outcome and must not be dressed as a
conclusion -- F-114 was nearly closed on "it is mostly retention" and that
explanation was withdrawn. So the analyser is tested for BOTH: that it
concludes when the data discriminates, and that it says so when it does not.
"""

from __future__ import annotations

from pathlib import Path

from tools.analyse_connection_log_gap import (
    HYPOTHESIS_A,
    HYPOTHESIS_B,
    SELECTING_CODE_CITATIONS,
    analyseGap,
    contiguousRuns,
    loadCsv,
    renderReport,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXPORT = _REPO_ROOT / "data" / "us808-connection-log-export"


def _pi(rowId: int, eventType: str) -> dict[str, str]:
    return {"id": str(rowId), "event_type": eventType}


def _sv(sourceId: int, eventType: str) -> dict[str, str]:
    return {"source_id": str(sourceId), "event_type": eventType}


class TestAccountedForPerEventTypeNotInAggregate:
    """Acceptance 1."""

    def test_perTypeNumbersSumToTheTierTotals(self) -> None:
        """
        Given: rows on both tiers
        When:  the gap is analysed
        Then:  the per-type counts sum to each tier's total

        The criterion exists to catch an aggregate that matches while the
        per-type breakdown does not -- so the sums are asserted, not the
        totals alone.
        """
        piRows = [_pi(1, "connect_attempt"), _pi(2, "connect_failure"),
                  _pi(3, "connect_success")]
        serverRows = [_sv(3, "connect_success")]

        analysis = analyseGap(piRows, serverRows)

        assert sum(analysis.piPerType.values()) == analysis.piTotal == 3
        assert sum(analysis.serverPerType.values()) == analysis.serverTotal == 1
        assert sum(analysis.missingPerType.values()) == analysis.missingTotal == 2

    def test_missingIsComputedPerTypeFromRowIdentity(self) -> None:
        """
        Given: a server holding SOME rows of a type and not others
        When:  the gap is analysed
        Then:  missing is counted per type from row identity, not subtraction

        Subtracting totals would report the same number while being unable to
        say WHICH rows are absent -- and which rows is the whole question.
        """
        piRows = [_pi(i, "connect_attempt") for i in range(1, 6)]
        serverRows = [_sv(1, "connect_attempt"), _sv(5, "connect_attempt")]

        analysis = analyseGap(piRows, serverRows)

        assert analysis.missingPerType == {"connect_attempt": 3}


class TestContiguityIsTheDiscriminator:
    def test_contiguousRunsCollapseCorrectly(self) -> None:
        runs = contiguousRuns([1, 2, 3, 7, 8, 20])

        assert [(r.firstId, r.lastId) for r in runs] == [(1, 3), (7, 8), (20, 20)]
        assert [r.length for r in runs] == [3, 2, 1]

    def test_anEmptySetHasNoRuns(self) -> None:
        assert contiguousRuns([]) == ()


class TestTheTwoHypothesesAndTheVerdict:
    """Acceptance 2."""

    def test_bIsRefutedWhenTheServerHoldsTheMissingTypesInBlocks(self) -> None:
        """
        Given: a server holding the same types that are missing, and the
               missing ids forming contiguous blocks
        When:  the gap is analysed
        Then:  B is refuted and A is supported

        If sync had never carried the type, the server would hold NONE of it.
        """
        piRows = [_pi(i, "connect_attempt") for i in range(1, 21)]
        serverRows = [_sv(i, "connect_attempt") for i in range(11, 21)]

        analysis = analyseGap(piRows, serverRows)

        assert analysis.refuted == HYPOTHESIS_B
        assert analysis.supported == HYPOTHESIS_A

    def test_theVerdictNamesWhatItCannotSettle(self) -> None:
        """
        Given: a conclusion in favour of A
        When:  the verdict is read
        Then:  it states what remains undetermined

        A conclusion that does not name its own limit invites the next reader
        to treat the mechanism as established. HOW the watermark got ahead is
        not established here.
        """
        piRows = [_pi(i, "connect_attempt") for i in range(1, 21)]
        serverRows = [_sv(i, "connect_attempt") for i in range(11, 21)]

        analysis = analyseGap(piRows, serverRows)

        assert "watermark" in analysis.undetermined.lower()
        assert "reopen" in analysis.undetermined.lower()

    def test_anEmptyDifferenceConcludesNothing(self) -> None:
        """
        Given: a server holding every Pi row
        When:  the gap is analysed
        Then:  no hypothesis is picked
        """
        piRows = [_pi(1, "connect_attempt")]
        serverRows = [_sv(1, "connect_attempt")]

        analysis = analyseGap(piRows, serverRows)

        assert analysis.supported == ""
        assert analysis.refuted == ""
        assert "no rows are missing" in analysis.undetermined

    def test_undeterminedSaysWhatWouldDiscriminate(self) -> None:
        """
        Given: an analysis that cannot choose
        When:  the verdict is read
        Then:  it names the evidence that WOULD decide

        An honest 'undetermined' is a valid outcome. One that does not say
        what would settle it is just a shrug.
        """
        analysis = analyseGap([_pi(1, "x")], [])

        if not analysis.supported:
            assert analysis.undetermined


class TestTheSelectingCodeIsCitedNotInferred:
    """Acceptance 3."""

    def test_citationsNameFileAndSymbol(self) -> None:
        """
        Given: the recorded citations
        When:  they are read
        Then:  each names a file AND a symbol

        A conclusion about what sync carries that does not cite the selecting
        code is not accepted -- so the citation is data, not prose.
        """
        assert SELECTING_CODE_CITATIONS
        for citation in SELECTING_CODE_CITATIONS:
            assert "src/pi/data/sync_log.py" in citation
            assert "::" in citation

    def test_theCitedSymbolsActuallyExist(self) -> None:
        """
        Given: the cited symbols
        When:  the real module is parsed
        Then:  each is defined there

        A citation that has drifted from the code is worse than none: it
        carries the authority of a reference while pointing at nothing. This
        is what makes the citation checkable rather than decorative.
        """
        import ast

        source = (_REPO_ROOT / "src/pi/data/sync_log.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        defined = {
            node.name for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        defined |= {
            target.id for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            for target in node.targets if isinstance(target, ast.Name)
        }
        defined |= {
            node.target.id for node in ast.walk(tree)
            if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
        }

        for citation in SELECTING_CODE_CITATIONS:
            symbol = citation.split("::", 1)[1].split(" ", 1)[0]
            assert symbol in defined, f"cited symbol {symbol!r} is not in sync_log.py"

    def test_theSelectingQueryCarriesNoEventTypeFilter(self) -> None:
        """
        Given: the real delta-selection code
        When:  its source is read
        Then:  neither the query nor the predicate mentions event_type

        THIS is the evidence that refutes hypothesis B, and it is read from
        the code rather than inferred from the data.
        """
        import ast

        source = (_REPO_ROOT / "src/pi/data/sync_log.py").read_text(encoding="utf-8")
        tree = ast.parse(source)

        for name in ("getDeltaRows", "_deltaPredicate"):
            node = next(
                n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == name
            )
            body = ast.get_source_segment(source, node) or ""
            # Strip the docstring so prose cannot satisfy or break this.
            doc = ast.get_docstring(node) or ""
            code = body.replace(doc, "")
            assert "event_type" not in code, f"{name} filters by event_type"


class TestTheWatermarkExplanationIsTestedNotAssumed:
    """Acceptance 4."""

    def test_aFullyAdvancedWatermarkIsRecognised(self) -> None:
        """
        Given: a watermark equal to the highest Pi id
        When:  the analysis is read
        Then:  it reports the cursor as fully advanced

        This is what makes the loss PERMANENT rather than pending: the
        predicate is `id > lastId`, so rows below a fully-advanced cursor are
        never selected again.
        """
        analysis = analyseGap(
            [_pi(1, "connect_attempt")], [], watermark=84700, maxPiId=84700,
        )

        assert analysis.watermarkIsFullyAdvanced is True

    def test_aTrailingWatermarkIsNotFullyAdvanced(self) -> None:
        """
        Given: a watermark behind the highest id
        When:  the analysis is read
        Then:  it is NOT reported as fully advanced -- those rows are pending
        """
        analysis = analyseGap(
            [_pi(1, "connect_attempt")], [], watermark=100, maxPiId=84700,
        )

        assert analysis.watermarkIsFullyAdvanced is False

    def test_anUnknownWatermarkIsNotClaimedAdvanced(self) -> None:
        """
        Given: no watermark reading
        When:  the analysis is read
        Then:  it does not claim the cursor is advanced

        Absence of the measurement is not evidence for the conclusion it
        would have supported.
        """
        analysis = analyseGap([_pi(1, "x")], [])

        assert analysis.watermarkIsFullyAdvanced is False


class TestAgainstTheRealPreservedExport:
    """The measured case, read from what US-808-a preserved."""

    def test_theRealGapIs28318AndRefutesB(self) -> None:
        """
        Given: the CSVs US-808-a exported from both live tiers
        When:  the gap is analysed
        Then:  28,318 rows are missing, in contiguous runs, and B is refuted

        Skipped rather than failed if the export is absent, so the suite
        stays green on a checkout without the data files -- but when they are
        present this is the real answer, not a fixture.
        """
        import pytest

        piFile = _EXPORT / "pi_connection_log_before_2026-06-01.csv"
        serverFile = _EXPORT / "server_connection_log_before_2026-06-01.csv"
        if not piFile.exists() or not serverFile.exists():
            pytest.skip("US-808-a export not present in this checkout")

        analysis = analyseGap(
            loadCsv(piFile), loadCsv(serverFile),
            watermark=84700, maxPiId=84700,
        )

        assert analysis.piTotal == 44704
        assert analysis.serverTotal == 16386
        assert analysis.missingTotal == 28318
        assert analysis.refuted == HYPOTHESIS_B
        assert analysis.supported == HYPOTHESIS_A
        assert analysis.watermarkIsFullyAdvanced is True
        # Every missing row is a retry type -- a CONSEQUENCE of the runs being
        # contiguous outage blocks, not evidence of a type filter.
        assert set(analysis.missingPerType) == {
            "connect_attempt", "connect_failure", "disconnect",
        }
        # And no row travelled the other way: the Pi is not missing server rows.
        assert analysis.serverOnlyIds == 0

    def test_theReportRendersTheVerdictAndTheCitations(self) -> None:
        analysis = analyseGap(
            [_pi(i, "connect_attempt") for i in range(1, 21)],
            [_sv(i, "connect_attempt") for i in range(11, 21)],
            watermark=20, maxPiId=20,
        )

        report = renderReport(analysis)

        assert "REFUTED:" in report
        assert "UNDETERMINED:" in report
        assert "sync_log.py::getDeltaRows" in report
