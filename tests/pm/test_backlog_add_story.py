################################################################################
# File Name: test_backlog_add_story.py
# Purpose/Description: Tests for `backlog_set --add-story` (US-669 / F-118) --
#                      the story-CREATION path that stamps every
#                      schema-required field so the metadata drift cannot
#                      start. Covers the five validationCriteria plus the
#                      safe-write, id-allocation and refusal guarantees.
# Author: Rex (Ralph / windows-dev)
# Creation Date: 2026-09-04
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-04    | Rex (Ralph)  | Initial implementation -- US-669 TDD
# ================================================================================
################################################################################

"""Tests for the ``backlog_set --add-story`` story-creation path (US-669).

WHY THESE TESTS LOOK LIKE THIS
------------------------------
The drift this story closes is a DUPLICATED CONSTANT: a tool that restates
``REQUIRED_STORY_FIELDS`` instead of reading it goes stale the moment the schema
grows, and nothing goes red. So the load-bearing test here is NOT "the tool
stamps twelve fields" -- that assertion passes just as happily against a copied
list. It is :func:`test_addStory_schemaGrowsANewRequiredField_toolRefusesWithoutBeingEdited`,
which grows the schema at runtime and requires the tool to notice. That test is
the whole VC3, and a copied list fails it.

The second load-bearing shape is the REFUSAL side. Every "refused" test asserts
the backlog's BYTES are unchanged, not merely that the exit code was non-zero --
per VC2, and because a tool that half-wrote a 900 KB file on a share with no git
is the failure mode acceptance #6 was written from (a real 22,588-byte loss on
2026-08-31).
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from tools.pm import backlog_schema, backlog_set

FIXTURES = Path(__file__).parent / "fixtures"

# A complete, semantically-populated story. Unicode on purpose: the PM's real
# prose is full of arrows and the red-circle emoji, and the venv is cp1252
# (US-466). A tool that crashes on its own data is not a tool.
GOOD_ARGS = [
    "--add-story",
    "--story-parent", "F-103",
    "--story-title", "The tool stamps metadata → the drift cannot start",
    "--story-goal", "As the PM, I want one command that files a compliant story.",
    "--story-dod", "\U0001f534 SSOT: backlog_schema.REQUIRED_STORY_FIELDS is read, never restated.",
    "--story-dod", "END STATE: validateBacklog accepts the result unmodified.",
    "--story-vc", "run the tool with every semantic field", "backlog validates",
]


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def share(tmp_path, monkeypatch):
    """A throwaway fleet share holding a valid v2 backlog + a story counter.

    Points $FLEET_SHARE at it so the tool exercises the REAL resolution path
    (:func:`tools.pm._paths.resolveShareRoot`) rather than a root that
    production callers never inject.
    """
    pmDir = tmp_path / "pm"
    pmDir.mkdir(parents=True)
    data = json.loads((FIXTURES / "v2_backlog_sample.json").read_text(encoding="utf-8"))
    (pmDir / "backlog.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (pmDir / "story_counter.json").write_text(
        json.dumps({"description": "Global story counter.",
                    "lastUpdated": "2026-09-01",
                    "nextId": "US-361"}, indent=2) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FLEET_SHARE", str(tmp_path))
    return tmp_path


def backlogPath(share: Path) -> Path:
    return share / "pm" / "backlog.json"


def counterPath(share: Path) -> Path:
    return share / "pm" / "story_counter.json"


def digest(path: Path) -> str:
    """Hash a file's BYTES -- VC2 asks for byte-identity, not for equal JSON."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(argv: list[str]) -> int:
    return backlog_set.main(argv)


def loadStories(share: Path) -> list[dict]:
    return json.loads(backlogPath(share).read_text(encoding="utf-8"))["stories"]


# ---------------------------------------------------------------------------
# VC1 -- a fully-supplied story validates with no edits
# ---------------------------------------------------------------------------

def test_addStory_everySemanticFieldSupplied_resultValidatesUnmodified(share):
    """
    Given: a backlog that validates and every required semantic field supplied
    When: --add-story runs
    Then: the REAL validateBacklog accepts the written file with no edits
    """
    # Arrange
    before = json.loads(backlogPath(share).read_text(encoding="utf-8"))
    assert backlog_schema.validateBacklog(before) is before

    # Act
    rc = run(GOOD_ARGS)

    # Assert -- through the real validator, over the file that was actually written
    assert rc == 0
    written = json.loads(backlogPath(share).read_text(encoding="utf-8"))
    backlog_schema.validateBacklog(written)
    assert len(written["stories"]) == len(before["stories"]) + 1


def test_addStory_stampsCreatedAtAndUpdatedAtFromTheRunDate(share):
    """
    Given: a story created today
    When: the record is read back
    Then: createdAt and updatedAt are both the run date (VC1, second half)
    """
    import datetime as dt

    run(GOOD_ARGS)

    story = loadStories(share)[-1]
    today = dt.date.today().isoformat()
    assert story["createdAt"] == today
    assert story["updatedAt"] == today


def test_addStory_defaultsConditionalOutcomesAndTasksToEmptyLists(share):
    """
    Given: neither conditionalOutcomes nor tasks supplied
    When: the story is created
    Then: both are present as EMPTY LISTS -- metadata may be defaulted (AC #4)
    """
    run(GOOD_ARGS)

    story = loadStories(share)[-1]
    assert story["conditionalOutcomes"] == []
    assert story["tasks"] == []


def test_addStory_carriesTheSuppliedSemanticContentVerbatim(share):
    """
    Given: Unicode-bearing goal/DoD/validationCriteria
    When: the story is round-tripped through the writer
    Then: the content is byte-for-byte what was supplied -- not re-encoded,
          not escaped, not truncated (US-466 PYTHONUTF8 hardening).
    """
    run(GOOD_ARGS)

    story = loadStories(share)[-1]
    assert story["title"] == "The tool stamps metadata → the drift cannot start"
    assert story["definitionOfDone"][0].startswith("\U0001f534 SSOT:")
    assert story["validationCriteria"] == [
        {"action": "run the tool with every semantic field", "outcome": "backlog validates"}
    ]
    # ensure_ascii=False: the arrow is a real character on disk, not →.
    assert "→" in backlogPath(share).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# VC2 -- missing SEMANTIC content refuses and writes NOTHING
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("dropped", ["--story-goal", "--story-dod", "--story-vc"])
def test_addStory_missingSemanticField_refusesAndLeavesTheFileByteIdentical(
    share, dropped, capsys
):
    """
    Given: a create request omitting goal, definitionOfDone or validationCriteria
    When: the tool runs
    Then: non-zero exit, the missing name reported, and backlog.json is
          BYTE-IDENTICAL -- the file hash, not just the exit code (VC2).
    """
    # Arrange -- drop one flag and its value(s)
    argv: list[str] = []
    i = 0
    while i < len(GOOD_ARGS):
        if GOOD_ARGS[i] == dropped:
            i += 3 if dropped == "--story-vc" else 2
            continue
        argv.append(GOOD_ARGS[i])
        i += 1
    backlogBefore = digest(backlogPath(share))
    counterBefore = digest(counterPath(share))

    # Act
    rc = run(argv)

    # Assert
    assert rc != 0
    assert digest(backlogPath(share)) == backlogBefore
    assert digest(counterPath(share)) == counterBefore
    fieldName = {"--story-goal": "goal",
                 "--story-dod": "definitionOfDone",
                 "--story-vc": "validationCriteria"}[dropped]
    assert fieldName in capsys.readouterr().err


def test_addStory_severalSemanticFieldsMissing_reportsEVERYName_notJustTheFirst(
    share, capsys
):
    """
    Given: goal, definitionOfDone AND validationCriteria all omitted
    When: the tool runs
    Then: all three names appear -- a one-at-a-time refusal makes the drift
          look small and costs the PM three round trips (F-118's thesis).
    """
    rc = run(["--add-story", "--story-parent", "F-103", "--story-title", "T"])

    assert rc != 0
    err = capsys.readouterr().err
    for name in ("goal", "definitionOfDone", "validationCriteria"):
        assert name in err


def test_addStory_emptyStringGoal_isRefused_notAcceptedAsSchemaValid(share):
    """
    Given: --story-goal "" (present but semantically empty)
    When: the tool runs
    Then: refused. A story that is SCHEMA-valid and semantically empty is worse
          than a missing one, because the lint then certifies it (PM Rule 7).

    This is the pin that separates "the key exists" from "content was supplied".
    A tool checking only ``"goal" in args`` passes every other test in this file.
    """
    argv = [a if a != "As the PM, I want one command that files a compliant story."
            else "   " for a in GOOD_ARGS]
    backlogBefore = digest(backlogPath(share))

    assert run(argv) != 0
    assert digest(backlogPath(share)) == backlogBefore


def test_addStory_neverInventsAPlaceholderToSatisfyTheSchema(share):
    """
    Given: a refused create (no goal supplied)
    When: the backlog is re-read
    Then: no story was appended at all.

    Stated as an ABSENCE OF A RECORD rather than as an exit code, because the
    forbidden behaviour (AC #5) is *writing* a placeholder, and a tool that
    exits non-zero AFTER appending would satisfy an exit-code-only assertion.
    """
    idsBefore = {s["id"] for s in loadStories(share)}

    argv = [a for i, a in enumerate(GOOD_ARGS)
            if a != "--story-goal" and GOOD_ARGS[i - 1] != "--story-goal"]
    run(argv)

    assert {s["id"] for s in loadStories(share)} == idsBefore


# ---------------------------------------------------------------------------
# VC3 -- the field list is READ, not RESTATED
# ---------------------------------------------------------------------------

def test_addStory_schemaGrowsANewRequiredField_toolRefusesWithoutBeingEdited(
    share, monkeypatch, capsys
):
    """
    Given: a new required field added to REQUIRED_STORY_FIELDS at runtime
    When: the tool runs UNCHANGED
    Then: it refuses and names the field.

    THIS IS VC3 AND IT IS THE POINT OF THE STORY. It fails if anyone copies the
    field list into the tool -- and it also fails if the tool does
    ``from backlog_schema import REQUIRED_STORY_FIELDS``, because that binds a
    COPY at import time. Only a call-time module-attribute read survives.
    """
    grown = frozenset(backlog_schema.REQUIRED_STORY_FIELDS | {"owner"})
    monkeypatch.setattr(backlog_schema, "REQUIRED_STORY_FIELDS", grown)
    backlogBefore = digest(backlogPath(share))

    rc = run(GOOD_ARGS)

    assert rc != 0, "the tool restated the field list instead of reading it"
    assert "owner" in capsys.readouterr().err
    assert digest(backlogPath(share)) == backlogBefore


def test_buildStory_schemaGrowsANewRequiredField_refusesAtItsOWNLevel(monkeypatch):
    """
    Given: a grown REQUIRED_STORY_FIELDS
    When: buildStory is called DIRECTLY, with no validateBacklog downstream
    Then: it refuses and names the field.

    WHY THIS IS SEPARATE FROM THE END-TO-END VC3 TEST ABOVE, and it is the most
    important comment in this file. Two independent mechanisms read the schema:
    buildStory's own missing-field check, and the synthetic-wrapper
    ``validateBacklog`` (which re-reads the module global at
    backlog_schema.py:90). Through the CLI they alibi each other -- MEASURED:
    restating the list as a literal inside buildStory left the end-to-end test
    GREEN, because the wrapper caught it instead; and deleting the wrapper left
    it green too, because buildStory caught it.

    Neither was pinned. A test that passes cannot say WHICH nested guarantee
    produced the pass -- only going at each level separately can. This one
    reaches buildStory with nothing behind it.
    """
    grown = frozenset(backlog_schema.REQUIRED_STORY_FIELDS | {"owner"})
    monkeypatch.setattr(backlog_schema, "REQUIRED_STORY_FIELDS", grown)

    with pytest.raises(backlog_set.StoryCreationError) as excinfo:
        backlog_set.buildStory(
            storyId="US-999", parent="F-103", title="T", goal="g",
            definitionOfDone=["d"],
            validationCriteria=[{"action": "a", "outcome": "o"}],
        )

    assert "owner" in str(excinfo.value)


def test_addStory_validationCriteriaPairIsSemanticallyEmpty_isRefused(share):
    """
    Given: a validationCriteria pair whose OUTCOME is an empty string
    When: the tool runs
    Then: refused, nothing written.

    The pair is STRUCTURALLY present, so the non-empty-list semantic check
    passes it; only the real validator inspects inside the pair. This is the
    test that makes the synthetic-wrapper check load-bearing rather than
    decorative -- deleting the wrapper leaves every other test in this file
    green, and lets a story ship with an unfalsifiable criterion.
    """
    argv = [a if a != "backlog validates" else "  " for a in GOOD_ARGS]
    backlogBefore = digest(backlogPath(share))

    assert run(argv) != 0
    assert digest(backlogPath(share)) == backlogBefore


def test_theSemanticFieldsAreASubsetOfWhatTheSchemaRequires(share):
    """
    Given: the tool's SEMANTIC_STORY_FIELDS selection
    When: compared with the schema
    Then: every one is genuinely required.

    Guards the OTHER drift direction: a semantic field the schema does not
    require would make the tool refuse work the backlog would have accepted.
    """
    assert set(backlog_set.SEMANTIC_STORY_FIELDS) <= set(
        backlog_schema.REQUIRED_STORY_FIELDS
    )


def test_noPmToolRestatesTheRequiredFieldList(share):
    """
    Given: every module under tools/pm/
    When: parsed
    Then: exactly ONE assigns REQUIRED_STORY_FIELDS -- backlog_schema itself.

    Parsed with ``ast``, not grepped, so this ban can be DESCRIBED in comments
    and docstrings without firing on its own explanation. (A textual sweep
    cannot tell an assignment from a description of one -- learned the hard way
    in US-675.)
    """
    import ast

    toolsPm = Path(backlog_set.__file__).parent
    assigners = []
    for path in sorted(toolsPm.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            targets = (node.targets if isinstance(node, ast.Assign)
                       else [node.target] if isinstance(node, ast.AnnAssign) else [])
            for target in targets:
                if isinstance(target, ast.Name) and target.id == "REQUIRED_STORY_FIELDS":
                    assigners.append(path.name)

    assert assigners == ["backlog_schema.py"], (
        f"REQUIRED_STORY_FIELDS is restated in {assigners} -- a second copy is "
        f"the drift US-669 exists to end. Import it from backlog_schema instead."
    )


# ---------------------------------------------------------------------------
# VC4 -- Rule 11, no orphans
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("parent,why", [
    ("F-999", "a Feature id that does not exist"),
    ("E-001", "an EPIC id -- the plausible mistake, and it must NOT be accepted"),
    ("US-359", "a STORY id"),
    ("", "empty"),
])
def test_addStory_parentIsNotAnExistingFeature_refusesAndWritesNothing(
    share, parent, why
):
    """
    Given: a parent that is not an existing Feature id
    When: the tool runs
    Then: refused, nothing written (Rule 11 -- every Story has a Feature parent)

    E-001 is the case worth having: it EXISTS in the file, so a membership test
    written against the wrong collection accepts it and files a story whose
    parent is an Epic.
    """
    argv = [parent if GOOD_ARGS[i - 1] == "--story-parent" else a
            for i, a in enumerate(GOOD_ARGS)]
    backlogBefore = digest(backlogPath(share))
    counterBefore = digest(counterPath(share))

    assert run(argv) != 0, why
    assert digest(backlogPath(share)) == backlogBefore
    assert digest(counterPath(share)) == counterBefore


# ---------------------------------------------------------------------------
# VC5 -- duplicate ids, and the counter
# ---------------------------------------------------------------------------

def test_addStory_idAlreadyExists_refusesAndLeavesTheCounterUnchanged(share):
    """
    Given: an explicit --story-id that is already in the backlog
    When: the tool runs
    Then: refused, no duplicate appended, and the counter is UNCHANGED (VC5)
    """
    argv = [*GOOD_ARGS, "--story-id", "US-359"]
    backlogBefore = digest(backlogPath(share))
    counterBefore = digest(counterPath(share))

    assert run(argv) != 0
    assert digest(backlogPath(share)) == backlogBefore
    assert digest(counterPath(share)) == counterBefore
    assert [s["id"] for s in loadStories(share)].count("US-359") == 1


def test_addStory_bumpsBothCountersSoTheNextCallerCannotCollide(share):
    """
    Given: story_counter.nextId US-361 and counters.story 360
    When: two stories are created back to back
    Then: they get DIFFERENT ids, and both counters advanced (AC #7)

    Asserted by CREATING TWICE rather than by reading the counter once: the
    claim is "the next caller cannot collide", and only a second caller can
    witness that.
    """
    assert run(GOOD_ARGS) == 0
    firstId = loadStories(share)[-1]["id"]
    assert run(GOOD_ARGS) == 0
    secondId = loadStories(share)[-1]["id"]

    assert firstId != secondId
    counter = json.loads(counterPath(share).read_text(encoding="utf-8"))
    data = json.loads(backlogPath(share).read_text(encoding="utf-8"))
    assert counter["nextId"] not in {firstId, secondId}
    assert data["counters"]["story"] == int(secondId.split("-")[1])


@pytest.mark.parametrize("stale", ["counterFile", "backlogCounter", "both"])
def test_addStory_anIdSourceHasFallenBehind_allocatesAboveEVERYSource(share, stale):
    """
    Given: one (or both) of the two counters trailing the ids actually present
    When: a story is created
    Then: the new id is above every existing story.

    PARAMETRIZED ONE SOURCE AT A TIME ON PURPOSE. Staling only ONE leaves the
    other still correct, so a tool that reads just that one still gets the right
    answer and the test cannot see the difference -- MEASURED: an earlier
    single-case version of this test was survived by a mutation that dropped
    every source but ``counters.story``. Each source must be shown to be
    individually INSUFFICIENT.

    This is the live shape, not a hypothetical: on 2026-09-04 the real files
    read counters.story 678 against a highest story of US-680, so
    ``counters.story + 1`` would have minted US-679 -- an id already taken.
    """
    counter = json.loads(counterPath(share).read_text(encoding="utf-8"))
    data = json.loads(backlogPath(share).read_text(encoding="utf-8"))
    if stale in ("counterFile", "both"):
        counter["nextId"] = "US-100"
    if stale in ("backlogCounter", "both"):
        data["counters"]["story"] = 300
    counterPath(share).write_text(json.dumps(counter, indent=2) + "\n", encoding="utf-8")
    backlogPath(share).write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    assert run(GOOD_ARGS) == 0

    newId = loadStories(share)[-1]["id"]
    assert int(newId.split("-")[1]) > 359, (
        f"{newId} is at or below the highest story already present (US-359) -- "
        f"the '{stale}' source was trusted on its own"
    )


def test_addStory_idSourcesDisagree_saysSo_ratherThanPaperingOverIt(share, capsys):
    """
    Given: counters that disagree with each other and with the records
    When: a story is created
    Then: the disagreement is REPORTED.

    A counter that has fallen behind is a symptom of something else writing the
    file. Silently allocating above it heals this run and hides the cause.
    """
    counter = json.loads(counterPath(share).read_text(encoding="utf-8"))
    counter["nextId"] = "US-100"
    counterPath(share).write_text(json.dumps(counter, indent=2) + "\n", encoding="utf-8")

    assert run(GOOD_ARGS) == 0
    assert "US-100" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# AC #6 -- it must WRITE SAFELY on this share
# ---------------------------------------------------------------------------

def test_addStory_writeFailsMidLanding_backlogIsByteIdenticalAndNoTempRemains(
    share, monkeypatch
):
    """
    Given: os.replace raising (a share hiccup at the moment of landing)
    When: the tool runs
    Then: backlog.json is BYTE-IDENTICAL and no .tmp is left behind.

    An in-place ``open(path, "w")`` that then raises has already destroyed a
    22,588-byte file on this share (2026-08-31). backlog.json is ~900 KB on a
    tree with no git and no revert, so this is the guarantee that matters most.
    """
    backlogBefore = digest(backlogPath(share))

    def boom(src, dst):
        raise OSError("share hiccup")

    monkeypatch.setattr(backlog_set.os, "replace", boom)

    assert run(GOOD_ARGS) != 0
    assert digest(backlogPath(share)) == backlogBefore
    assert list((share / "pm").glob("*.tmp")) == []


def test_addStory_writesViaTempPlusReplace_neverTruncatingInPlace(share, monkeypatch):
    """
    Given: a successful create
    When: the write is observed
    Then: no writable handle was ever opened on backlog.json itself.

    The mechanism, not just its happy-path outcome: the failure test above
    passes for a tool that got lucky, this one fails for a tool that truncates.
    """
    target = str(backlogPath(share))
    opened: list[str] = []
    realOpen = backlog_set.open if hasattr(backlog_set, "open") else open

    def spy(file, mode="r", *args, **kwargs):
        if "w" in mode or "a" in mode or "+" in mode:
            opened.append(os.fspath(file))
        return realOpen(file, mode, *args, **kwargs)

    monkeypatch.setattr("builtins.open", spy)

    assert run(GOOD_ARGS) == 0
    assert target not in opened, "backlog.json was opened for writing in place"
    assert any(p.endswith(".tmp") for p in opened), "no temp file was used"


def test_addStory_backlogWriteFails_theCounterHasSTILLAdvanced_soAGapNotACollision(
    share, monkeypatch
):
    """
    Given: the backlog's landing fails but the counter's succeeded
    When: the run aborts
    Then: the counter has advanced -- the id is burned, leaving a GAP.

    Pins the deliberate ORDERING, which no happy-path test can see. Land the
    backlog first and a lost counter bump hands the SAME id to the next caller;
    that is the collision AC #7 exists to prevent. A gap is harmless, a
    duplicate is not, so the counter goes first ON PURPOSE.
    """
    counterBefore = json.loads(counterPath(share).read_text(encoding="utf-8"))["nextId"]
    realReplace = os.replace

    def failOnlyTheBacklog(src, dst):
        if str(dst).endswith("backlog.json"):
            raise OSError("share hiccup landing the backlog")
        return realReplace(src, dst)

    monkeypatch.setattr(backlog_set.os, "replace", failOnlyTheBacklog)

    assert run(GOOD_ARGS) != 0

    counterAfter = json.loads(counterPath(share).read_text(encoding="utf-8"))["nextId"]
    assert counterAfter != counterBefore, (
        "the counter did not advance -- the next caller will be handed an id "
        "that this run already tried to use"
    )
    assert all(s["id"] != counterBefore for s in loadStories(share))


def test_addStory_dryRun_reportsThePlanAndWritesNothing(share, capsys):
    """
    Given: --dry-run
    When: a valid create is requested
    Then: the story is described, and BOTH files are byte-identical
    """
    backlogBefore = digest(backlogPath(share))
    counterBefore = digest(counterPath(share))

    assert run([*GOOD_ARGS, "--dry-run"]) == 0

    assert "DRY RUN" in capsys.readouterr().out
    assert digest(backlogPath(share)) == backlogBefore
    assert digest(counterPath(share)) == counterBefore


# ---------------------------------------------------------------------------
# the Feature lookup this subcommand depends on
# ---------------------------------------------------------------------------

def test_findFeature_readsTheV2TopLevelFeatureList(share):
    """
    Given: a v2.0.0 backlog (features at the TOP LEVEL, not nested under epics)
    When: findFeature is asked for one
    Then: it is found.

    Before US-669 this walked ``epics[].features[]`` -- the v1 shape. No epic in
    the v2 backlog carries a nested features[], so it returned None for EVERY
    feature id and the whole --feature branch of backlog_set exited 2. Measured
    on the live 914 KB backlog on 2026-09-04.
    """
    data = json.loads(backlogPath(share).read_text(encoding="utf-8"))

    found = backlog_set.findFeature(data, "F-103")

    assert found is not None
    assert found["id"] == "F-103"
    assert backlog_set.findFeature(data, "F-999") is None


def test_findFeature_stillReadsTheLegacyNestedV1Shape():
    """
    Given: a pre-migration v1 backlog with features nested under epics
    When: findFeature is asked for one
    Then: it is still found -- the v2 fix must not orphan the archived shape.
    """
    v1 = {"epics": [{"id": "E-1", "features": [{"id": "B-037", "status": "pending"}]}]}

    assert backlog_set.findFeature(v1, "B-037")["id"] == "B-037"
