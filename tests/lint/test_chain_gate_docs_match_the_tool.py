################################################################################
# File Name: test_chain_gate_docs_match_the_tool.py
# Purpose/Description: Standing-rule lint (US-618 / F-136) -- no document in this
#     repo may claim that the chain merge is gated on EVERY sprint in a V0.X
#     chain carrying a `validatedAt` stamp. The gate is the CHAIN TIP ALONE.
#
#     THE DEFECT THIS LINT EXISTS FOR, AND ITS MEASURED COST: the tool was
#     corrected to the CIO 2026-05-23 chain-end-merge rule; its documentation was
#     not. `.claude/commands/chain-validated.md` went on describing pre-rule
#     behaviour in seven places, `/sprint-validated` repeated it in three, and
#     `tools/pm/README.md` plus the tool's OWN module docstring repeated it in
#     three more -- twelve occurrences across four files, of which the US-618
#     story text named four. The PM read the doc, believed it, and groomed the
#     whole of Sprint 76 around a 27-sprint validation-ledger "debt" that does
#     not exist and never blocked a merge. That is the cost on record.
#
#     WHY THIS IS A LINT AND NOT A ONE-OFF EDIT: a fact killed in one file on
#     this project has survived in three others before (US-570 found a third
#     consumer copy of a retired UI surface; US-571 found the same for the
#     magnetometer). Correcting twelve strings without a standing rule just
#     resets the clock.
#
#     THE GATE IS MEASURED, NOT QUOTED. `test_gateIsChainTipOnly_measured` and
#     its siblings EXECUTE `aggregateChain` against synthetic chains rather than
#     asserting anything about the source text. That is deliberate: US-618's
#     conditionalOutcome forbids "fixing" the mismatch by editing the tool to
#     match the old doc, and these tests are what would catch someone doing it.
#     If the tool is ever changed so that an earlier sprint's `validatedAt: null`
#     blocks READY, `test_earlierSprintsNull_doNotBlockREADY` goes red and names
#     the rule it broke.
#
#     GROUNDING -- measured 2026-08-28 by running the shipped tool:
#       chain V0.29.2=null, V0.29.9=null, V0.29.30=stamped -> READY,   exit 0
#       chain V0.29.2=ok,   V0.29.9=ok,   V0.29.30=null    -> INCOMPLETE, exit 1
#       chain prefix matching no sprint at all             -> INCOMPLETE, exit 1
#                                                             chainTipVersion=None
#     The third case is why the docs must distinguish the two causes of
#     INCOMPLETE: an empty chain (wrong --chain prefix) reports the same status
#     as an unvalidated tip, and only `chainTipVersion` tells them apart.
# Author: Claude (Ralph / Rex)
# Creation Date: 2026-08-28
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-08-28    | Claude       | Initial -- US-618, chain-tip gating doc/code
#               |              | agreement lint.
# ================================================================================
################################################################################

"""Lint: chain-merge docs must describe chain-TIP gating, and the tool must do it."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
import tempfile
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TOOL_PATH = _REPO_ROOT / "tools" / "pm" / "chain_validate_aggregate.py"
_COMMANDS_DIR = _REPO_ROOT / ".claude" / "commands"
_TOOLS_README = _REPO_ROOT / "tools" / "pm" / "README.md"

# The line of chain_validate_aggregate.py the docs are required to cite as their
# source of truth (US-618 AC-5). Pinned so that a doc pointing at a line number
# cannot quietly rot into pointing at nothing -- see test_citedGateLine_*.
_CITED_GATE_LINE = 238


# ------------------------------------------------------------------------------
# Loading the tool
# ------------------------------------------------------------------------------
# chain_validate_aggregate.py does `from tools.pm._paths import SHARE_ROOT`, and
# _paths resolves that lazily from $FLEET_SHARE with no fallback -- so merely
# IMPORTING the tool is a configuration error when the share is unconfigured.
#
# These tests never read share data (they pass explicit paths), so that
# requirement is incidental to the import, not to the behaviour under test.
# Pointing $FLEET_SHARE at a throwaway directory for the duration keeps this lint
# runnable in an environment without the share instead of ERRORING during
# collection -- the failure mode filed as I-us553, where nine tests/pm modules
# vanish from the count entirely depending on one environment variable.
def _loadTool():  # noqa: ANN202 -- test helper
    """Load tools/pm/chain_validate_aggregate.py as a module."""
    if not os.environ.get("FLEET_SHARE"):
        os.environ["FLEET_SHARE"] = tempfile.mkdtemp(prefix="us618_shareless_")

    spec = importlib.util.spec_from_file_location("_us618_chain_aggregate", _TOOL_PATH)
    assert spec is not None and spec.loader is not None, (
        f"chain_validate_aggregate.py not found at {_TOOL_PATH} -- US-318 ships this tool"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_us618_chain_aggregate"] = mod
    spec.loader.exec_module(mod)
    return mod


def _writeSprint(directory: Path, version: str, validatedAt: str | None) -> Path:
    """Write a minimal sprint.json carrying just the validation block the tool reads."""
    path = directory / f"sprint.{version}.json"
    path.write_text(
        json.dumps(
            {
                "sprint": f"synthetic {version}",
                "validation": {
                    "currentVersion": version,
                    "validatedAt": validatedAt,
                    "validatedBy": "test" if validatedAt else None,
                    "validatesFeatures": ["F-001"],
                    "bigDefinitionOfDone": [f"clause for {version}"],
                },
            }
        ),
        encoding="utf-8",
    )
    return path


# ------------------------------------------------------------------------------
# The retired wordings, verbatim, with provenance
# ------------------------------------------------------------------------------
# Each entry is the ACTUAL text that shipped before US-618, quoted from the file
# and line named. They serve two purposes: they document what was wrong, and
# `test_everyRetiredWording_isCaughtByABan` proves the ban patterns below would
# have caught the real defect -- without needing to re-introduce it into the
# tree. A ban list that matches nothing real is an inert guard.
RETIRED_WORDINGS: list[tuple[str, str]] = [
    (
        "chain-validated.md:15",
        "After every sprint in the chain has `/sprint-validated` run + CIO "
        "confirms whole chain green",
    ),
    (
        "chain-validated.md:17",
        "**WHEN to run**: every sprint in a V0.X chain has "
        "`validation.validatedAt` populated on `dev`",
    ),
    (
        "chain-validated.md:22",
        "- Any sprint in the chain still has `validatedAt: null` (chain INCOMPLETE)",
    ),
    (
        "chain-validated.md:77",
        "- chainStatus = INCOMPLETE -> at least one sprint lacks `validatedAt`;",
    ),
    (
        "chain-validated.md:91",
        "# Strict gate -- exit 1 if any sprint lacks validatedAt",
    ),
    (
        "chain-validated.md:260",
        "| 2 | `--strict` exits 1 (INCOMPLETE) | Run `/sprint-validated` on "
        "missing sprint(s); re-run |",
    ),
    (
        "chain-validated.md:277",
        "every sprint in the chain has its stamp AND CIO confirms whole-chain green.",
    ),
    (
        "sprint-validated.md:8",
        "`/chain-validated` does that at chain end (after every sprint in the "
        "V0.X chain has its own `/sprint-validated` stamp AND CIO confirms "
        "whole-chain green).",
    ),
    (
        "sprint-validated.md:163",
        "The chain merge runs once at chain end via `/chain-validated` after "
        "every sprint in the V0.X chain has its own `/sprint-validated` stamp "
        "AND CIO confirms whole-chain green.",
    ),
    (
        "sprint-validated.md:211",
        "The chain merge to main happens via `/chain-validated` once every "
        "sprint in the chain has its own stamp AND CIO confirms whole-chain green.",
    ),
    (
        "tools/pm/README.md:108",
        "reports whether the chain is READY (all sprints validated) or INCOMPLETE.",
    ),
    (
        "tools/pm/README.md:122",
        "# CI gate -- exit 1 if any sprint in chain lacks validatedAt:",
    ),
    (
        "chain_validate_aggregate.py:8",
        "and reports whether the chain is READY (all sprints\nvalidated) or "
        "INCOMPLETE (one+ sprint's validatedAt still null).",
    ),
]

# Patterns describing the RETIRED claim. Matching runs against whitespace-
# collapsed text (see _collapse) because every one of these documents wraps its
# prose -- chain-validated.md:17 splits the offending sentence across three
# lines, and a line-oriented scan would miss it.
#
# The gap bounds below are `.{0,N}` and NOT `[^.]{0,N}`. Excluding the period
# looks like a cheap way to stop a match running across a sentence boundary, and
# it is exactly wrong here: every sentence this lint hunts contains a VERSION
# STRING -- "every sprint in a V0.X chain has ...". `[^.]` cannot cross the dot
# in `V0.X`, so the first draft of this list silently failed to match three of
# the twelve real sites. test_everyRetiredWording_isCaughtByABan caught it; the
# length bounds do the sentence-scoping instead.
BANNED_PATTERNS: list[tuple[str, str]] = [
    (
        r"all sprints\s+validated",
        "claims READY means every sprint is validated; READY means the chain TIP is",
    ),
    (
        r"one\+ sprint",
        "claims INCOMPLETE means one-or-more sprints are unstamped; it means the TIP is",
    ),
    (
        r"any sprint\b.{0,40}\blacks?\b.{0,30}validatedAt",
        "claims any sprint lacking validatedAt gates; only the chain TIP gates",
    ),
    (
        r"at least one sprint\b.{0,40}(lacks?|null)",
        "claims one unstamped sprint blocks the merge; only the chain TIP blocks it",
    ),
    (
        r"[Aa]ny sprint in the chain still has.{0,30}validatedAt.{0,10}null",
        "lists an earlier sprint's null stamp as a stop condition; it is the "
        "EXPECTED state",
    ),
    (
        r"every sprint in (?:a|the).{0,30}chain has.{0,60}"
        r"(validatedAt|stamp|/sprint-validated)",
        "makes the merge conditional on every sprint being stamped; the gate is "
        "the chain TIP alone",
    ),
    (
        r"missing sprint\(s\)",
        "tells the operator to stamp several sprints; there is only ever one to "
        "stamp -- the chain TIP",
    ),
]

# Documents that must never carry the retired claim. Globbed rather than listed
# so a NEW command doc repeating it is caught on the day it lands.
def _docSurface() -> list[Path]:
    """Every doc surface subject to this rule."""
    docs = sorted(_COMMANDS_DIR.glob("*.md"))
    docs.append(_TOOLS_README)
    docs.append(_TOOL_PATH)  # the tool's own module docstring is a doc surface too
    return docs


def _collapse(text: str) -> str:
    """Collapse all whitespace runs to a single space.

    Wrapped prose is the reason: the retired sentence at chain-validated.md:17
    spanned three source lines, so a per-line scan reports clean on a file that
    still carries the defect.
    """
    return re.sub(r"\s+", " ", text)


# ------------------------------------------------------------------------------
# Group 1 -- the gate itself, MEASURED by execution
# ------------------------------------------------------------------------------


class TestTheGateIsChainTipOnly:
    """Execute the shipped tool. These are what catch someone inverting US-618."""

    def test_earlierSprintsNull_doNotBlockREADY(self, tmp_path: Path) -> None:
        """
        Given: a chain whose earlier patches are unstamped and whose TIP is stamped
        When: the chain is aggregated
        Then: chainStatus is READY -- the state the corrected docs describe

        This is the assertion the whole story rests on. US-618's conditionalOutcome
        forbids making the tool match the old doc; if anyone does, this goes red.
        """
        tool = _loadTool()
        paths = [
            _writeSprint(tmp_path, "V0.29.2", None),
            _writeSprint(tmp_path, "V0.29.9", None),
            _writeSprint(tmp_path, "V0.29.30", "2026-08-28T00:00:00Z"),
        ]

        result = tool.aggregateChain(paths, "V0.29")

        assert result["chainStatus"] == "READY", (
            "Two earlier sprints carry validatedAt: null and the chain tip is "
            "stamped. Under the CIO 2026-05-23 chain-end-merge rule that is READY. "
            "If this failed, the TOOL was changed to match the retired "
            "documentation -- which is precisely what US-618 forbids."
        )
        assert result["chainTipVersion"] == "V0.29.30"
        assert result["unvalidatedSprints"] == ["V0.29.2", "V0.29.9"], (
            "earlier nulls must still be REPORTED -- they are informational "
            "context (chain_validate_aggregate.py:188), just not a gate"
        )

    def test_unvalidatedTip_blocksREADY(self, tmp_path: Path) -> None:
        """
        Given: a chain whose earlier patches are all stamped but whose TIP is not
        When: the chain is aggregated
        Then: chainStatus is INCOMPLETE

        The control for the test above: without it, "READY" would be equally
        consistent with a gate that never blocks anything.
        """
        tool = _loadTool()
        paths = [
            _writeSprint(tmp_path, "V0.29.2", "2026-08-01T00:00:00Z"),
            _writeSprint(tmp_path, "V0.29.9", "2026-08-02T00:00:00Z"),
            _writeSprint(tmp_path, "V0.29.30", None),
        ]

        result = tool.aggregateChain(paths, "V0.29")

        assert result["chainStatus"] == "INCOMPLETE"
        assert result["chainTipVersion"] == "V0.29.30"

    def test_emptyChain_isINCOMPLETE_withNullTip(self, tmp_path: Path) -> None:
        """
        Given: a --chain prefix that matches no sprint at all
        When: the chain is aggregated
        Then: chainStatus is INCOMPLETE and chainTipVersion is None

        The SECOND cause of INCOMPLETE, and the reason the corrected docs may not
        simply say "INCOMPLETE means the tip is unstamped". Only chainTipVersion
        separates a wrong --chain prefix from a genuinely unvalidated tip.
        """
        tool = _loadTool()
        paths = [_writeSprint(tmp_path, "V0.29.30", "2026-08-28T00:00:00Z")]

        result = tool.aggregateChain(paths, "V9.99")

        assert result["chainStatus"] == "INCOMPLETE"
        assert result["chainTipVersion"] is None
        assert result["sprintsInChain"] == []

    def test_strictExitCode_followsChainTip(self, tmp_path: Path) -> None:
        """
        Given: an unstamped earlier sprint and a stamped tip
        When: the CLI runs with --strict
        Then: it exits 0

        Exercises the exit code the docs quote, not just the dict the function
        returns -- `/chain-validated` Phase 2 branches on the exit status.
        """
        tool = _loadTool()
        paths = [
            _writeSprint(tmp_path, "V0.29.2", None),
            _writeSprint(tmp_path, "V0.29.30", "2026-08-28T00:00:00Z"),
        ]
        argv = ["--chain", "V0.29", "--json", "--strict", "--paths", *[str(p) for p in paths]]

        assert tool.main(argv) == 0

    def test_strictExitCode_isNonZeroWhenTipUnvalidated(self, tmp_path: Path) -> None:
        """
        Given: a stamped earlier sprint and an unstamped tip
        When: the CLI runs with --strict
        Then: it exits 1
        """
        tool = _loadTool()
        paths = [
            _writeSprint(tmp_path, "V0.29.2", "2026-08-01T00:00:00Z"),
            _writeSprint(tmp_path, "V0.29.30", None),
        ]
        argv = ["--chain", "V0.29", "--json", "--strict", "--paths", *[str(p) for p in paths]]

        assert tool.main(argv) == 1


# ------------------------------------------------------------------------------
# Group 2 -- no document may repeat the retired claim
# ------------------------------------------------------------------------------


class TestNoDocRepeatsTheRetiredClaim:
    """AC-1/AC-4/AC-6: the four cited lines, and every other copy of the claim."""

    @pytest.mark.parametrize("doc", _docSurface(), ids=lambda p: p.name)
    def test_docDoesNotClaimAllSprintGating(self, doc: Path) -> None:
        """
        Given: a command doc, tools/pm/README.md, or the tool's module docstring
        When: it is scanned for the retired all-sprints-must-be-stamped claim
        Then: no banned wording appears
        """
        collapsed = _collapse(doc.read_text(encoding="utf-8"))

        offences = []
        for pattern, why in BANNED_PATTERNS:
            for match in re.finditer(pattern, collapsed):
                start = max(0, match.start() - 60)
                offences.append(f"  ...{collapsed[start:match.end() + 60]}...\n     -> {why}")

        assert not offences, (
            f"{doc.relative_to(_REPO_ROOT)} describes the chain merge as gated on "
            f"every sprint's validatedAt. The gate is the CHAIN TIP alone "
            f"(chain_validate_aggregate.py:{_CITED_GATE_LINE}); earlier patches' "
            f"validatedAt: null is the EXPECTED state, not a debt.\n"
            + "\n".join(offences)
        )

    @pytest.mark.parametrize(
        "provenance,wording", RETIRED_WORDINGS, ids=[p for p, _ in RETIRED_WORDINGS]
    )
    def test_everyRetiredWording_isCaughtByABan(self, provenance: str, wording: str) -> None:
        """
        Given: the exact text that shipped at each of the twelve defect sites
        When: the ban patterns are applied to it
        Then: at least one pattern matches

        Proves the ban list would have caught the real defect, without
        re-introducing it. A ban list that matches nothing real passes on a
        broken tree and gets deleted at the first false alarm.
        """
        collapsed = _collapse(wording)

        assert any(re.search(pattern, collapsed) for pattern, _ in BANNED_PATTERNS), (
            f"No BANNED_PATTERNS entry matches the retired wording from "
            f"{provenance}:\n  {collapsed}\nThe ban list is inert for this site."
        )


# ------------------------------------------------------------------------------
# Group 3 -- the doc names its own source of truth (AC-5)
# ------------------------------------------------------------------------------


class TestTheDocNamesItsSourceOfTruth:
    """AC-5: the doc must cite the tool, and the citation must not rot."""

    def test_chainValidatedDoc_citesTheGateLine(self) -> None:
        """
        Given: .claude/commands/chain-validated.md
        When: it is searched for a pointer to the gating expression
        Then: it names chain_validate_aggregate.py and the gate line number
        """
        text = _collapse((_COMMANDS_DIR / "chain-validated.md").read_text(encoding="utf-8"))

        assert re.search(rf"chain_validate_aggregate\.py:{_CITED_GATE_LINE}\b", text), (
            "chain-validated.md must point at "
            f"chain_validate_aggregate.py:{_CITED_GATE_LINE} as its source of "
            "truth (US-618 AC-5). The doc drifted from the tool once already "
            "because nothing in it named the tool as authoritative."
        )

    def test_citedGateLine_stillHoldsTheGate(self) -> None:
        """
        Given: the line number the doc cites
        When: that line of chain_validate_aggregate.py is read
        Then: it is still the chainStatus/chainTip gating expression

        A line-number citation is an inert pointer the moment the file shifts.
        This fails loudly and tells the next agent to re-point the doc rather
        than letting it silently address a blank line.
        """
        line = _TOOL_PATH.read_text(encoding="utf-8").splitlines()[_CITED_GATE_LINE - 1]

        assert "chainStatus" in line and "chainTip" in line, (
            f"chain_validate_aggregate.py:{_CITED_GATE_LINE} no longer holds the "
            f"gating expression -- it now reads:\n    {line.strip()!r}\n"
            "The docs cite this line by number. Re-point them and update "
            "_CITED_GATE_LINE here."
        )


# ------------------------------------------------------------------------------
# Group 4 -- controls: what must SURVIVE the correction
# ------------------------------------------------------------------------------


class TestTheRealGateSurvives:
    """The corrected doc must not lose the requirement it never had wrong."""

    def test_cioWholeChainConfirmation_isStillRequired(self) -> None:
        """
        Given: the corrected chain-validated.md
        When: it is read for the CIO's whole-chain confirmation requirement
        Then: that requirement is still present

        The retired claim was about validatedAt STAMPS. The requirement that the
        CIO confirm the whole chain actually WORKS IRL is a different fact, it is
        Phase 2, and it is still true. Deleting it while "fixing" the stamp claim
        would remove the only real gate on chain quality.
        """
        text = _collapse((_COMMANDS_DIR / "chain-validated.md").read_text(encoding="utf-8"))

        assert "fully functional working" in text, (
            "Phase 2's CIO confirmation is the real chain-quality gate and must "
            "survive the US-618 correction"
        )
        assert re.search(r"CIO (explicitly )?confirms", text)

    def test_earlierNullsAreDocumentedAsExpected(self) -> None:
        """
        Given: the corrected chain-validated.md
        When: it is read for how earlier patches' null stamps are characterised
        Then: it says they are expected, not a debt

        AC-4 asks for more than deleting the wrong sentence: the reader has to
        learn what the right state IS, or the next PM re-derives the same wrong
        conclusion from the absence of any statement.
        """
        text = _collapse((_COMMANDS_DIR / "chain-validated.md").read_text(encoding="utf-8"))

        assert re.search(r"EXPECTED state", text), (
            "the doc must state that earlier patches' validatedAt: null is the "
            "expected steady state under chain-end-merge (US-618 AC-4)"
        )

    def test_theCostOnRecordIsStated(self) -> None:
        """
        Given: the corrected chain-validated.md
        When: it is read for why the correction is worded emphatically
        Then: it names US-618 and the sprint groomed on the false premise

        AC-3 asks for this explicitly: a bare correction reads as pedantry and
        gets softened by the next editor.
        """
        text = _collapse((_COMMANDS_DIR / "chain-validated.md").read_text(encoding="utf-8"))

        assert "US-618" in text
        assert re.search(r"Sprint 76|sprint \(76\)", text), (
            "the doc must record that a whole sprint was groomed against this "
            "defect (US-618 AC-3)"
        )


# ------------------------------------------------------------------------------
# Group 5 -- guard the guard
# ------------------------------------------------------------------------------


class TestTheGuardItself:
    """A lint that silently scans nothing is worse than no lint."""

    def test_docSurfaceIsNotEmpty(self) -> None:
        """
        Given: the doc surface this lint scans
        When: it is enumerated
        Then: it contains the command docs plus both tool surfaces
        """
        surface = _docSurface()
        names = {p.name for p in surface}

        assert len(surface) >= 5, f"doc surface collapsed to {surface}"
        assert {"chain-validated.md", "sprint-validated.md", "README.md",
                "chain_validate_aggregate.py"} <= names
        for path in surface:
            assert path.is_file(), f"doc surface names a missing file: {path}"

    def test_bannedPatternsAreAllValidRegexes(self) -> None:
        """
        Given: the ban list
        When: each pattern is compiled
        Then: none raises

        A malformed pattern would otherwise surface as an error inside whichever
        doc happened to be scanned first, blaming the document for the lint's bug.
        """
        for pattern, why in BANNED_PATTERNS:
            re.compile(pattern)
            assert why.strip(), f"{pattern} has no explanation"

    def test_collapseJoinsWrappedProse(self) -> None:
        """
        Given: a sentence wrapped across source lines
        When: it is collapsed
        Then: it reads as one line

        Pins the property that makes the scan work on chain-validated.md:17,
        whose offending sentence spanned three lines.
        """
        assert _collapse("every sprint in a\nV0.X chain has\n  validatedAt") == (
            "every sprint in a V0.X chain has validatedAt"
        )
