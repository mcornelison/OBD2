################################################################################
# File Name: test_repair_ralph_agents_roster.py
# Purpose/Description: Tests for `repair_ralph_agents.py` (US-664 / F-137) --
#                      the roster size must be READ from the file under repair,
#                      never assumed to be 4. Covers the three
#                      validationCriteria plus the max_agent preservation, the
#                      safe-write and the prose sweep.
# Author: Rex (Ralph / windows-dev)
# Creation Date: 2026-09-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-04    | Rex (Ralph)  | Initial implementation -- US-664 TDD
# ================================================================================
################################################################################

"""Tests for the roster-size independence of ``repair_ralph_agents.py`` (US-664).

WHY THIS FILE EXISTS
--------------------
``repair_ralph_agents.py`` had ZERO test references anywhere in this repository
before this commit -- not a unit test, not an incidental import, nothing. The
story's framing ("nobody had exercised it since the roster shrank") understates
it: nobody had exercised it at all. So none of the guarantees asserted here are
inherited; every one of them is established for the first time.

WHY THESE TESTS LOOK LIKE THIS
------------------------------
The named defect is a literal ``!= 4`` in the post-repair safety check. But
fixing ONLY that literal makes the tool ACTIVELY HARMFUL rather than merely
useless, and that is the load-bearing observation in this file:

    the reconstruction also hardcodes ``"max_agent": 4`` into the output it
    writes.

Today the ``!= 4`` refusal MASKS that -- the tool declines before it can write.
Remove the refusal alone and a 2-agent roster is silently repaired to
``max_agent: 4``, which is worse than the refusal it replaced: a wrong answer
delivered confidently. :func:`test_repair_twoAgentRoster_maxAgentPreserved` is
the pin for that, and it is UNREACHABLE against today's code because the
refusal fires first. A test that cannot run against the defect is not evidence,
so it is paired with the roster-preservation tests that CAN.

The other structural choice: the pre-repair count must be derived
INDEPENDENTLY of the reconstruction, or the guard is vacuous. Counting the
agents in the rebuilt document and comparing it against the same tail that
built it can only ever agree with itself. So the count is taken from the RAW
text by structure, and the guard compares two numbers produced by two different
code paths.
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest

from tools.pm import repair_ralph_agents as tool

# ---------------------------------------------------------------------------
# Fixture builders
#
# These mirror the on-disk shape of the REAL ralph_agents.json exactly (2-space
# indent for the document, 4 spaces for each agent object, 6 for its fields),
# because the tool's boundary regex is sensitive to that indentation. A fixture
# with tidier whitespace would make the tool look more robust than it is.
# ---------------------------------------------------------------------------

_CORRUPT_NOTE = 'US-999 CLOSED passes:true. He said "done" and left.'

_AGENT_BLOCK = """    {{
      "id": {agentId},
      "name": "{name}",
      "type": "windows-dev",
      "status": "unassigned",
      "taskid": "",
      "lastCheck": "2026-09-04",
      "note": "{note}"
    }}"""


def buildRoster(
    agentIds: list[int],
    maxAgent: int | None = None,
    corruptIndex: int | None = 0,
    notes: dict[int, str] | None = None,
    corruptNote: str = _CORRUPT_NOTE,
) -> str:
    """Render a ralph_agents.json, optionally corrupted the way Rex corrupts it.

    Args:
        agentIds: The ``id`` of each agent, in document order. Not required to
            be contiguous or sorted -- neither is guaranteed by anything.
        maxAgent: Value for the ``max_agent`` key. ``None`` omits the key.
        corruptIndex: Position (not id) of the agent whose note carries an
            UNESCAPED quote -- the actual recurring bug. ``None`` leaves the
            document valid.
        notes: Optional note text per agent id, for the over-count probes.
        corruptNote: The corrupt note's text. It MUST carry an unescaped quote.
            Overriding it is how the probes get raw, unescaped JSON into the
            document: a VALID JSON string can never hold a bare ``"``, so the
            only place that text can legally exist is inside the corruption --
            which is precisely the file this tool always reads.

    Returns:
        The rendered document as text.
    """
    blocks = []
    for position, agentId in enumerate(agentIds):
        note = (notes or {}).get(agentId, f"agent {agentId} routine note")
        if position == corruptIndex:
            note = corruptNote
        blocks.append(
            _AGENT_BLOCK.format(agentId=agentId, name=f"Agent{agentId}", note=note)
        )

    header = "{\n"
    if maxAgent is not None:
        header += f'  "max_agent": {maxAgent},\n'
    header += '  "agents": [\n'
    return header + ",\n".join(blocks) + "\n  ]\n}\n"


def writeRoster(tmp_path: Path, raw: str) -> Path:
    """Write a roster fixture and return its path."""
    target = tmp_path / "ralph_agents.json"
    target.write_text(raw, encoding="utf-8", newline="")
    return target


def md5(path: Path) -> str:
    """Digest a file's exact bytes -- 'unchanged' means unchanged, not 'still parses'."""
    return hashlib.md5(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# VC1 + VC2 -- the roster size is read, not assumed
# ---------------------------------------------------------------------------


class TestTheRosterSizeIsReadNotAssumed:
    """VC1/VC2: corrupt a roster of ANY size and the repair preserves it."""

    @pytest.mark.parametrize("size", [2, 3, 4, 5])
    def test_repair_corruptRoster_preservesEveryAgent(self, tmp_path, size):
        """
        Given: a roster of `size` agents whose first note is corrupt
        When: the repair runs
        Then: it exits 0 and every agent id survives

        Parametrized across 2 AND 4 deliberately. A test written only at 4
        passes against the defect; a test written only at 2 leaves "did the fix
        break the case that used to work?" unanswered. 3 and 5 are there
        because nothing guarantees the roster is either of the two sizes anyone
        has thought about.
        """
        ids = list(range(1, size + 1))
        path = writeRoster(tmp_path, buildRoster(ids, maxAgent=size))

        assert tool.main(["--path", str(path)]) == 0

        repaired = json.loads(path.read_text(encoding="utf-8"))
        assert [a["id"] for a in repaired["agents"]] == ids

    def test_repair_twoAgentRoster_preservesTheSecondAgentVerbatim(self, tmp_path):
        """
        Given: the live roster shape -- 2 agents, the second one untouched
        When: the repair runs
        Then: agent 2's fields are preserved exactly, note included

        'Preserves both agents' must mean the CONTENT survived, not merely that
        two objects came out the other side.
        """
        raw = buildRoster([1, 2], maxAgent=2, notes={2: "Agent2 has been idle since 2026-07-20"})
        path = writeRoster(tmp_path, raw)

        assert tool.main(["--path", str(path)]) == 0

        agents = json.loads(path.read_text(encoding="utf-8"))["agents"]
        second = next(a for a in agents if a["id"] == 2)
        assert second["name"] == "Agent2"
        assert second["note"] == "Agent2 has been idle since 2026-07-20"
        assert second["lastCheck"] == "2026-09-04"

    def test_repair_shortensTheCorruptNoteToThePointer(self, tmp_path):
        """
        Given: a corrupt roster
        When: the repair runs
        Then: agent 1's note is the short pointer -- the repair still repairs

        The control for every test above: preserving the roster must not have
        been achieved by declining to do the job.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2))

        assert tool.main(["--path", str(path)]) == 0

        agents = json.loads(path.read_text(encoding="utf-8"))["agents"]
        assert agents[0]["note"] == tool.DEFAULT_REX_NOTE
        assert "done" not in agents[0]["note"]


class TestMaxAgentIsPreservedNotInvented:
    """The half the ``!= 4`` refusal was hiding.

    ``max_agent`` is the other half of the roster SSOT named in this story's
    first acceptance clause. The reconstruction hardcoded ``"max_agent": 4``,
    so removing the count refusal on its own converts a useless tool into a
    destructive one: a 2-agent roster comes back claiming 4.
    """

    @pytest.mark.parametrize("size", [2, 3, 4, 5])
    def test_repair_maxAgentSurvivesTheRepair(self, tmp_path, size):
        """
        Given: a corrupt roster declaring max_agent = `size`
        When: the repair runs
        Then: max_agent still reads `size`

        LOAD-BEARING. This is the test that stops the fix for US-664 from
        introducing a worse defect than the one it closes.
        """
        path = writeRoster(tmp_path, buildRoster(list(range(1, size + 1)), maxAgent=size))

        assert tool.main(["--path", str(path)]) == 0

        assert json.loads(path.read_text(encoding="utf-8"))["max_agent"] == size

    def test_repair_maxAgentDisagreeingWithTheArray_isPreservedAndReported(
        self, tmp_path, capsys
    ):
        """
        Given: a corrupt roster whose max_agent (4) disagrees with its 2 agents
        When: the repair runs
        Then: it repairs, PRESERVES the stated 4, and warns about the disagreement

        The tool must not silently 'correct' a disagreement it did not cause.
        Refusing would be this story's own defect restored -- declining a file
        for a pre-existing condition that has nothing to do with the corruption
        being repaired. Reporting is the honest middle: the operator decides.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=4))

        assert tool.main(["--path", str(path)]) == 0

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["max_agent"] == 4
        assert len(payload["agents"]) == 2
        assert "max_agent" in capsys.readouterr().out.lower()

    def test_repair_maxAgentQuotedInsideANote_isNotMistakenForTheDeclaration(
        self, tmp_path
    ):
        """
        Given: NO declared max_agent, and a corrupt note quoting `"max_agent": 9`
        When: the repair runs
        Then: 2 is derived from the roster -- the 9 in the prose is not read

        THE ABSENT DECLARATION IS WHAT MAKES THIS TEST ABLE TO FAIL. With a
        max_agent present in the header, a whole-document search finds the real
        declaration first anyway, so the note is never reached and the test
        proves nothing -- which is how my first version of it let the mutation
        survive. The recovery is scoped to the document HEAD, and only a file
        with nothing in the head to find can witness that scoping.

        Rex's notes quote this file's own keys at other people routinely; the
        note being repaired here is a note ABOUT the roster. Reporting a number
        lifted from prose is the same class of wrong answer as the literal it
        replaced.
        """
        note = 'the header said "max_agent": 9 and that was wrong'
        raw = buildRoster([1, 2], maxAgent=None, corruptNote=note)
        path = writeRoster(tmp_path, raw)
        assert not tool.isValidJson(path), "fixture is not actually corrupt"

        assert tool.main(["--path", str(path)]) == 0

        assert json.loads(path.read_text(encoding="utf-8"))["max_agent"] == 2

    def test_repair_maxAgentAbsent_isDerivedFromTheArray(self, tmp_path):
        """
        Given: a corrupt roster with no max_agent key at all
        When: the repair runs
        Then: max_agent is derived from the surviving agent count, not from 4

        The story names two authorities -- max_agent and the agents[] array.
        With the first absent, the second answers. Inventing 4 here is the
        original defect wearing a fallback's clothes.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2, 3], maxAgent=None))

        assert tool.main(["--path", str(path)]) == 0

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert payload["max_agent"] == 3


# ---------------------------------------------------------------------------
# VC3 -- the safety check survives the fix
# ---------------------------------------------------------------------------


class TestTheSafetyCheckSurvivesTheFix:
    """VC3: a repair that would LOSE an agent must still refuse."""

    def test_repair_thatWouldDropAnAgent_refusesAndWritesNothing(self, tmp_path):
        """
        Given: a roster whose ids are out of document order -- 1, 5, 2
        When: the repair runs
        Then: it refuses with exit 1 and the file is byte-identical

        This reaches the drop through the REAL code path rather than through a
        patch. The boundary regex looks for id 2, which here sits in the THIRD
        object, so the reconstruction would splice agent 1 onto that tail and
        agent 5 would simply cease to exist. Nothing guarantees ids are sorted
        or contiguous, so this input is legal -- and it is exactly the shape
        the safety check exists for.
        """
        path = writeRoster(tmp_path, buildRoster([1, 5, 2], maxAgent=3))
        before = md5(path)

        assert tool.main(["--path", str(path)]) == 1
        assert md5(path) == before

    def test_repair_thatWouldDropAnAgent_namesBothCounts(self, tmp_path, capsys):
        """
        Given: the same drop case
        When: the repair refuses
        Then: the message states the before AND after counts

        'Refused' without the numbers is the failure this sprint keeps
        cataloguing -- a check that fires without informing. The operator has
        to be able to tell 'the tool is confused' from 'my file really did lose
        an agent'.
        """
        path = writeRoster(tmp_path, buildRoster([1, 5, 2], maxAgent=3))

        tool.main(["--path", str(path)])

        combined = capsys.readouterr()
        message = combined.out + combined.err
        assert "3" in message and "2" in message

    def test_rosterSizeRefusal_reportsADrop(self):
        """
        Given: 4 agents before, 3 after
        When: the guard is asked
        Then: it returns a refusal reason
        """
        assert tool.rosterSizeRefusal(4, 3) is not None

    def test_rosterSizeRefusal_reportsAnAddition(self):
        """
        Given: 2 agents before, 3 after
        When: the guard is asked
        Then: it ALSO refuses -- fabricating an agent is corruption too

        Tested directly because no legal input reaches this direction through
        the repair path: a roster with no agent 1 has its corruption in a block
        that lands inside the preserved tail, so the reconstruction fails to
        parse and returns earlier for a different reason. The guarantee is
        real, the end-to-end route to it is not, and an end-to-end test would
        therefore pin nothing here.
        """
        assert tool.rosterSizeRefusal(2, 3) is not None

    def test_rosterSizeRefusal_silentWhenThePreserveHeld(self):
        """
        Given: the count is unchanged
        When: the guard is asked
        Then: no refusal -- ANY size, not just 4

        The negative control. Without it, 'refuses on a drop' is also satisfied
        by a guard that refuses everything, which is the defect this story
        closes.
        """
        for size in (1, 2, 3, 4, 5, 12):
            assert tool.rosterSizeRefusal(size, size) is None


class TestThePreRepairCountIsIndependentOfTheReconstruction:
    """The guard is only worth having if its two sides are computed apart.

    ``countAgentBlocks`` reads the RAW text structurally; the post count comes
    from parsing the rebuilt document. Derive both from the same tail and the
    comparison can only agree with itself.
    """

    @pytest.mark.parametrize("size", [1, 2, 3, 4, 7])
    def test_countAgentBlocks_countsEveryAgentInACorruptFile(self, tmp_path, size):
        """
        Given: a CORRUPT roster of `size` agents
        When: the blocks are counted
        Then: the answer is `size`

        Counted on a corrupt file on purpose -- that is the only state the tool
        ever sees. A counter that needs valid JSON is no use here.
        """
        raw = buildRoster(list(range(1, size + 1)), maxAgent=size)
        assert tool.countAgentBlocks(raw) == size

    def test_countAgentBlocks_isNotFooledByRawJsonInsideTheCorruptNote(self, tmp_path):
        """
        Given: the corrupt note has an agent object pasted into it UNESCAPED
        When: the blocks are counted
        Then: the pasted one is not counted, and the repair still succeeds

        MY FIRST VERSION OF THIS TEST COULD NOT FAIL, and mutation is what said
        so. It put the quoted JSON in a VALID note, where the quotes are
        necessarily backslash-escaped -- so a deliberately loosened counter
        still did not match, and the mutation survived. The escaping was doing
        the work I was crediting to the pattern.

        The realistic fixture is this one. Rex pasting an unescaped JSON
        snippet into a note IS the bug this tool exists to repair, so the
        corrupt note is the one place raw `{ "id": ... }` can appear -- and it
        is the note the tool reads on every single run. The counter therefore
        requires a literal line break between `{` and `"id"`, which no JSON
        string can contain. A looser pattern over-counts here, the size guard
        then refuses a perfectly good file, and US-664's defect returns in a
        new costume.
        """
        pasted = 'I pasted { "id": 99, "name": "Ghost" } straight into the note'
        raw = buildRoster([1, 2], maxAgent=2, corruptNote=pasted)

        assert tool.countAgentBlocks(raw) == 2

        path = writeRoster(tmp_path, raw)
        assert not tool.isValidJson(path), "fixture is not actually corrupt"
        assert tool.main(["--path", str(path)]) == 0
        assert len(json.loads(path.read_text(encoding="utf-8"))["agents"]) == 2

    def test_countAgentBlocks_toleratesTheIndentationARepairLeavesBehind(self, tmp_path):
        """
        Given: a roster whose agent objects sit at a deeper indent
        When: the blocks are counted
        Then: they are still counted

        A repair splices text together and whitespace drifts. A counter pinned
        to exactly four leading spaces would silently under-count a
        previously-repaired file -- and this corruption has now recurred three
        times, so 'previously repaired' is the expected state, not an edge one.
        """
        raw = buildRoster([1, 2], maxAgent=2).replace("\n    {", "\n        {")
        assert tool.countAgentBlocks(raw) == 2


class TestTheRepairSurvivesItsOwnRecurrence:
    """Sprint 21, Sprint 24, 2026-08-31. The second repair must work too."""

    def test_repairTwice_stillPreservesTheWholeRoster(self, tmp_path):
        """
        Given: a roster repaired once, then corrupted again the same way
        When: the repair runs a second time
        Then: it still exits 0 with every agent and max_agent intact

        The tool's own output is its next input. Nothing had ever checked that
        the document it writes is a document it can read.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2, 3], maxAgent=3))
        assert tool.main(["--path", str(path)]) == 0

        firstPass = path.read_text(encoding="utf-8")
        recorrupted = firstPass.replace(
            json.dumps(tool.DEFAULT_REX_NOTE)[1:-1], _CORRUPT_NOTE
        )
        assert recorrupted != firstPass, "fixture failed to re-corrupt the file"
        path.write_text(recorrupted, encoding="utf-8", newline="")

        assert tool.main(["--path", str(path)]) == 0

        payload = json.loads(path.read_text(encoding="utf-8"))
        assert [a["id"] for a in payload["agents"]] == [1, 2, 3]
        assert payload["max_agent"] == 3


# ---------------------------------------------------------------------------
# The write itself
# ---------------------------------------------------------------------------


class TestTheWriteCannotDestroyTheFileItIsRepairing:
    """The share has no git, no snapshots and no undo (sprint keyReminders).

    An in-place ``write_text`` truncates BEFORE it can fail, so a failure part
    way through destroys the only copy of the file the tool exists to recover.
    That already cost a 22,588-byte file on this share on 2026-08-31.
    """

    def test_repair_whenTheFinalReplaceFails_theOriginalIsByteIdentical(
        self, tmp_path, monkeypatch
    ):
        """
        Given: a corrupt roster and a write that fails at the last moment
        When: the repair runs
        Then: it exits non-zero and the original bytes are untouched
        """
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2))
        before = md5(path)

        def boom(*args, **kwargs):
            raise OSError("share went away mid-write")

        monkeypatch.setattr(tool.os, "replace", boom)

        assert tool.main(["--path", str(path)]) != 0
        assert md5(path) == before

    def test_repair_whenTheWriteFails_noTemporaryFileIsLeftBehind(
        self, tmp_path, monkeypatch
    ):
        """
        Given: a write that fails at the last moment
        When: the repair gives up
        Then: the directory holds only the untouched roster

        Split from the success case deliberately: on a successful run the
        replace CONSUMES the temp file, so 'no temp file remains' is true for a
        reason that has nothing to do with cleanup, and a tool that never
        cleaned up would pass it. The failure path is the only one that can
        witness the cleanup -- and a half-written `ralph_agents.json.tmp` sat
        next to a corrupt `ralph_agents.json` is precisely the ambiguity the
        next person repairing this file does not need.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2))

        def boom(*args, **kwargs):
            raise OSError("share went away mid-write")

        monkeypatch.setattr(tool.os, "replace", boom)
        tool.main(["--path", str(path)])

        assert [p.name for p in tmp_path.iterdir()] == [path.name]

    def test_repair_leavesNoTemporaryFileBehind(self, tmp_path):
        """
        Given: a successful repair
        When: it finishes
        Then: the directory holds exactly the roster file

        A stray temp file beside a roster is the next reader's ambiguity.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2))

        assert tool.main(["--path", str(path)]) == 0
        assert [p.name for p in tmp_path.iterdir()] == [path.name]


# ---------------------------------------------------------------------------
# Everything the tool already promised
# ---------------------------------------------------------------------------


class TestThePreExistingContractIsUnchanged:
    """The fix must not quietly cost anything the tool already did."""

    def test_validFile_isANoOpAndSaysSo(self, tmp_path, capsys):
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2, corruptIndex=None))
        before = md5(path)

        assert tool.main(["--path", str(path)]) == 0
        assert md5(path) == before
        assert "no repair needed" in capsys.readouterr().out

    def test_missingFile_exitsTwo(self, tmp_path):
        assert tool.main(["--path", str(tmp_path / "absent.json")]) == 2

    def test_check_validFile_exitsZero(self, tmp_path, capsys):
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2, corruptIndex=None))
        assert tool.main(["--path", str(path), "--check"]) == 0
        assert "VALID" in capsys.readouterr().out

    def test_check_corruptFile_exitsOneAndWritesNothing(self, tmp_path):
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2))
        before = md5(path)

        assert tool.main(["--path", str(path), "--check"]) == 1
        assert md5(path) == before

    def test_dryRun_describesTheRepairAndWritesNothing(self, tmp_path, capsys):
        """
        Given: a corrupt roster
        When: --dry-run runs
        Then: exit 0, the file is byte-identical, and the plan is described

        Asserted on the FILE, not on the absence of the word 'wrote'. US-646:
        a 'DRY-RUN would: <command>' echo reads exactly like doing it.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2, 3], maxAgent=3))
        before = md5(path)

        assert tool.main(["--path", str(path), "--dry-run"]) == 0
        assert md5(path) == before
        assert "DRY-RUN" in capsys.readouterr().out

    def test_dryRun_reportsTheRosterItWouldPreserve(self, tmp_path, capsys):
        """
        Given: a 3-agent corrupt roster
        When: --dry-run runs
        Then: the output states 3, not a fixed roster size

        The dry run is the only thing an operator sees before authorising a
        write to a file with no undo. It reporting 'agents 2-4 preserved' on a
        3-agent file is the same false confidence as the literal in the check.
        """
        path = writeRoster(tmp_path, buildRoster([1, 2, 3], maxAgent=3))

        tool.main(["--path", str(path), "--dry-run"])

        assert "3" in capsys.readouterr().out

    def test_corruptionWiderThanTheNotePattern_refusesAndWritesNothing(self, tmp_path):
        """
        Given: a corrupt roster with no agent id 2 to anchor the tail on
        When: the repair runs
        Then: it refuses with exit 1 and nothing is written
        """
        path = writeRoster(tmp_path, buildRoster([1, 3], maxAgent=2))
        before = md5(path)

        assert tool.main(["--path", str(path)]) == 1
        assert md5(path) == before


# ---------------------------------------------------------------------------
# Acceptance clause 6 -- the prose must stop teaching the assumption
# ---------------------------------------------------------------------------


class TestTheFourAgentAssumptionIsGoneFromTheSource:
    """An executable predicate, not a count of edited lines.

    'Corrected in three places' is unverifiable, and this project has a
    catalogued history of sweeps that shipped one site short (US-595 went DoD 3
    -> gate 4 -> measured 9 -> shipped 8). So the claim is a predicate over the
    whole module.

    IT IS SPLIT IN TWO, AND THE SPLIT IS THE POINT. The PROSE must stop
    teaching the assumption, so that half is textual. The CODE must stop
    encoding it -- but a textual sweep for the removed literals also fires on
    the docstring that QUOTES them to explain the retirement, which is exactly
    what US-675 hit and what the first draft of this file hit again. Deleting
    the explanation to satisfy the grep would trade a defect for an
    unexplainable fix, so the code half reads the AST instead and prose is
    excluded by construction.
    """

    @staticmethod
    def _source() -> str:
        return Path(tool.__file__).read_text(encoding="utf-8")

    @staticmethod
    def _docstringNodes(tree: ast.AST) -> set[int]:
        """Identify every string constant that is a docstring, by identity."""
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if (
                    isinstance(first, ast.Expr)
                    and isinstance(first.value, ast.Constant)
                    and isinstance(first.value.value, str)
                ):
                    docstrings.add(id(first.value))
        return docstrings

    @pytest.mark.parametrize("phrase", ["2/3/4", "2-4", "agents 2", "Agents 2"])
    def test_noProseTeachesAFixedRoster(self, phrase):
        """The comments must not re-teach the assumption to the next reader."""
        assert phrase not in self._source()

    # A comparison operand that is talking about the roster rather than about a
    # loop index or a slice width.
    _ROSTER_OPERAND = re.compile(r"count|agent|len\(", re.IGNORECASE)

    def test_noRosterCountIsComparedAgainstANumericLiteral(self):
        """
        Given: the repaired module
        When: every comparison involving a roster count is read
        Then: none of them compares against an integer literal

        THE BAN IS SHAPED BY THE DEFECT, NOT BY THE DIGIT, and this test had to
        be narrowed TWICE to get there -- both times by a real false positive,
        which is the useful part of the record:

          * banning the integer 4 outright went red on
            `json.dumps(cleanAgent1, indent=4)`, a JSON indent width;
          * banning any integer literal in any comparison went red on `i > 0`,
            a loop index.

        Neither is a roster assumption, and special-casing the offending site
        each time would have left a ban that no longer means anything. The
        invariant that survives contact with the module is narrower and
        truer: a quantity DERIVED FROM THE ROSTER must be compared against
        another derived quantity, never against a literal -- `!= 4` today,
        `!= 2` after the next roster change.
        """
        tree = ast.parse(self._source())

        offenders = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            literals = [
                op
                for op in operands
                if isinstance(op, ast.Constant)
                and isinstance(op.value, int)
                and not isinstance(op.value, bool)
            ]
            aboutRoster = [
                op for op in operands if self._ROSTER_OPERAND.search(ast.unparse(op))
            ]
            if literals and aboutRoster:
                offenders.append(ast.unparse(node))
        assert offenders == []

    def test_theRosterLiteralBanIsNotVacuous(self):
        """
        Given: the defect restored -- a count compared against a literal 4
        When: the same predicate runs over it
        Then: it fires

        Without this, a ban narrowed twice is also satisfied by a predicate
        that has been narrowed into uselessness. US-635: an assertion that can
        only be satisfied one way is not evidence.
        """
        tree = ast.parse("if len(parsed.get('agents', [])) != 4:\n    pass\n")

        fired = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Compare):
                continue
            operands = [node.left, *node.comparators]
            if any(
                isinstance(op, ast.Constant) and isinstance(op.value, int) for op in operands
            ) and any(self._ROSTER_OPERAND.search(ast.unparse(op)) for op in operands):
                fired = True
        assert fired

    def test_noStringLiteralHardcodesAMaxAgentValue(self):
        """
        Given: the repaired module
        When: every non-docstring string constant is read
        Then: none of them writes a max_agent value into the output

        The reconstruction used to emit `"max_agent": 4` as text, which the
        integer sweep above would not see. Docstrings are excluded so the
        retirement note can name what it retired.
        """
        tree = ast.parse(self._source())
        docstrings = self._docstringNodes(tree)

        offenders = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and id(node) not in docstrings
            and isinstance(node.value, str)
            and re.search(r'"max_agent"\s*:\s*\d', node.value)
        ]
        assert offenders == []


class TestTheToolRunsWhenTheShareDoesNot:
    """A recovery tool must not decline for a reason unrelated to the job."""

    def test_explicitPath_neverTouchesTheShare(self, tmp_path, monkeypatch):
        """
        Given: $FLEET_SHARE cannot be resolved
        When: the tool runs against an explicit --path
        Then: it still repairs

        The share resolved EAGERLY at import, so importing this module was a
        configuration error even for a run that needs no share. That is this
        story's defect class one layer up: a refusal on a condition that has
        nothing to do with the file in front of you -- and it would bite in
        precisely the half-broken environment where someone reaches for a
        repair tool.
        """
        def boom() -> Path:
            raise RuntimeError("$FLEET_SHARE is not set")

        monkeypatch.setattr(tool._paths, "resolveShareRoot", boom)
        path = writeRoster(tmp_path, buildRoster([1, 2], maxAgent=2))

        assert tool.main(["--path", str(path)]) == 0
        assert len(json.loads(path.read_text(encoding="utf-8"))["agents"]) == 2
