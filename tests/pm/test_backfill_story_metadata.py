################################################################################
# File Name: test_backfill_story_metadata.py
# Purpose/Description: Tests for backfill_story_metadata.py -- the idempotent
#                      backlog.json metadata-drift repair tool (US-465 / F-118).
# Author: Rex (Ralph / windows-dev)
# Creation Date: 2026-07-13
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-07-13    | Rex (Ralph)  | Initial implementation -- US-465 TDD
# ================================================================================
################################################################################

"""Tests for backfill_story_metadata.py (US-465 backlog metadata backfill)."""
from __future__ import annotations

import json
from pathlib import Path

from offices.pm.scripts import backfill_story_metadata as bf
from offices.pm.scripts.backlog_schema import validateBacklog

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _story(**over):
    """A fully-compliant story dict; override any field via kwargs."""
    s = {
        "id": "US-999", "parent": "F-1", "title": "T",
        "type": "normal", "size": "S", "status": "complete",
        "goal": "g", "definitionOfDone": ["DoD"],
        "conditionalOutcomes": [], "validationCriteria": [{"action": "a", "outcome": "o"}],
        "createdAt": "2026-07-01", "updatedAt": "2026-07-01", "tasks": [],
    }
    s.update(over)
    return s


def _drifted(**over):
    """A story missing status/createdAt/updatedAt/conditionalOutcomes/tasks."""
    s = {
        "id": "US-500", "parent": "F-1", "title": "T",
        "type": "normal", "size": "M",
        "goal": "g", "definitionOfDone": ["DoD"],
        "validationCriteria": [{"action": "a", "outcome": "o"}],
    }
    s.update(over)
    return s


def _writeArchive(archiveDir: Path, filename: str, sprint: int, stories: list[dict]) -> None:
    """Write a minimal archived sprint.json fixture."""
    (archiveDir / filename).write_text(
        json.dumps({"sprint": sprint, "stories": stories}), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# buildSprintDateIndex
# ---------------------------------------------------------------------------

def test_buildSprintDateIndex_readsSprintFieldAndFilenameDate(tmp_path):
    _writeArchive(tmp_path, "sprint.archive.2026-07-01_105741Z.json", 50, [])
    _writeArchive(tmp_path, "sprint.archive.2026-07-05_112202Z.json", 55, [])
    idx = bf.buildSprintDateIndex(tmp_path)
    assert idx[50] == "2026-07-01"
    assert idx[55] == "2026-07-05"


def test_buildSprintDateIndex_multipleArchivesPerSprint_takesEarliestDate(tmp_path):
    # A sprint re-archived twice -> earliest close date wins.
    _writeArchive(tmp_path, "sprint.archive.2026-07-04_045400Z.json", 54, [])
    _writeArchive(tmp_path, "sprint.archive.2026-07-06_010000Z.json", 54, [])
    idx = bf.buildSprintDateIndex(tmp_path)
    assert idx[54] == "2026-07-04"


# ---------------------------------------------------------------------------
# buildStoryShipIndex
# ---------------------------------------------------------------------------

def test_buildStoryShipIndex_recordsPassedAndSeenSprints(tmp_path):
    _writeArchive(tmp_path, "sprint.archive.2026-07-01_105741Z.json", 50, [
        {"id": "US-408", "passes": True},
        {"id": "US-500", "passes": False},
    ])
    _writeArchive(tmp_path, "sprint.archive.2026-07-02_015912Z.json", 51, [
        {"id": "US-408", "passes": True},
    ])
    idx = bf.buildStoryShipIndex(tmp_path)
    assert idx["US-408"]["passed"] == {50, 51}
    assert idx["US-408"]["seen"] == {50, 51}
    # seen-but-never-passed
    assert idx["US-500"]["passed"] == set()
    assert idx["US-500"]["seen"] == {50}


# ---------------------------------------------------------------------------
# isCompliant
# ---------------------------------------------------------------------------

def test_isCompliant_fullyPopulatedStory_true():
    assert bf.isCompliant(_story()) is True


def test_isCompliant_missingRequiredField_false():
    assert bf.isCompliant(_drifted()) is False


def test_isCompliant_tasksNotAList_false():
    assert bf.isCompliant(_story(tasks="nope")) is False


# ---------------------------------------------------------------------------
# resolveStatus
# ---------------------------------------------------------------------------

def test_resolveStatus_missingStatusButShipped_complete():
    ship = {"US-500": {"passed": {50}, "seen": {50}}}
    status, _src = bf.resolveStatus(_drifted(id="US-500"), ship)
    assert status == "complete"


def test_resolveStatus_terminalStatusPreserved():
    ship = {"US-422": {"passed": set(), "seen": {51}}}
    status, src = bf.resolveStatus(_drifted(id="US-422", status="superseded"), ship)
    assert status == "superseded"
    assert "preserv" in src.lower()


def test_resolveStatus_staleNonTerminalButShipped_correctedToComplete():
    # US-458/459/460 shape: status=sprint-ready but shipped in an archive.
    ship = {"US-458": {"passed": {55}, "seen": {55}}}
    status, _src = bf.resolveStatus(_drifted(id="US-458", status="sprint-ready"), ship)
    assert status == "complete"


def test_resolveStatus_presentNonTerminalNotShipped_preserved():
    ship = {"US-446": {"passed": set(), "seen": set()}}
    status, _src = bf.resolveStatus(_drifted(id="US-446", status="pending"), ship)
    assert status == "pending"


def test_resolveStatus_absentAndNotShipped_conservativePending():
    status, src = bf.resolveStatus(_drifted(id="US-777"), {})
    assert status == "pending"
    assert "conservative" in src.lower()


# ---------------------------------------------------------------------------
# resolveDates
# ---------------------------------------------------------------------------

def test_resolveDates_archiveProxyUsesEarliestSprintDate():
    ship = {"US-421": {"passed": {52}, "seen": {51, 52}}}
    sprintDates = {51: "2026-07-02", 52: "2026-07-02"}
    created, updated, src = bf.resolveDates(
        _drifted(id="US-421"), ship, sprintDates, gitResolver=None, today="2026-07-13"
    )
    assert created == "2026-07-02"
    assert updated == "2026-07-02"
    assert "sprint-51" in src


def test_resolveDates_noArchiveUsesGitResolver():
    called = {}

    def gitResolver(storyId):
        called["id"] = storyId
        return "2026-07-04"

    created, updated, src = bf.resolveDates(
        _drifted(id="US-446"), {}, {}, gitResolver=gitResolver, today="2026-07-13"
    )
    assert called["id"] == "US-446"
    assert created == "2026-07-04"
    assert "git" in src.lower()


def test_resolveDates_noArchiveNoGit_fallsBackToTodayConservative():
    created, updated, src = bf.resolveDates(
        _drifted(id="US-446"), {}, {}, gitResolver=None, today="2026-07-13"
    )
    assert created == "2026-07-13"
    assert "conservative" in src.lower()


# ---------------------------------------------------------------------------
# backfillStory
# ---------------------------------------------------------------------------

def test_backfillStory_fillsAllMissingFields():
    ship = {"US-500": {"passed": {50}, "seen": {50}}}
    sprintDates = {50: "2026-07-01"}
    story, changed = bf.backfillStory(
        _drifted(id="US-500"), ship, sprintDates, gitResolver=None, today="2026-07-13"
    )
    assert changed is True
    assert story["status"] == "complete"
    assert story["conditionalOutcomes"] == []
    assert story["tasks"] == []
    assert story["createdAt"] == "2026-07-01"
    assert story["updatedAt"] == "2026-07-01"
    assert bf.isCompliant(story) is True


def test_backfillStory_recordsProvenanceMarker():
    ship = {"US-500": {"passed": {50}, "seen": {50}}}
    story, _ = bf.backfillStory(
        _drifted(id="US-500"), ship, {50: "2026-07-01"}, gitResolver=None, today="2026-07-13"
    )
    assert "metaBackfill" in story
    assert "sprint-50" in story["metaBackfill"]["dateSource"]


def test_backfillStory_doesNotAlterSemanticContent():
    ship = {"US-500": {"passed": {50}, "seen": {50}}}
    original = _drifted(id="US-500", title="Original Title", goal="Original Goal",
                        type="tech-debt", size="M", parent="F-118",
                        definitionOfDone=["orig DoD"])
    story, _ = bf.backfillStory(original, ship, {50: "2026-07-01"},
                                gitResolver=None, today="2026-07-13")
    assert story["title"] == "Original Title"
    assert story["goal"] == "Original Goal"
    assert story["type"] == "tech-debt"
    assert story["size"] == "M"
    assert story["parent"] == "F-118"
    assert story["definitionOfDone"] == ["orig DoD"]


def test_backfillStory_compliantStory_noOp():
    story, changed = bf.backfillStory(
        _story(), {}, {}, gitResolver=None, today="2026-07-13"
    )
    assert changed is False


def test_backfillStory_preservesExistingDateWhenPartiallyPresent():
    ship = {"US-500": {"passed": {50}, "seen": {50}}}
    # already has createdAt but missing updatedAt (+ other fields) -> non-compliant
    story, changed = bf.backfillStory(
        _drifted(id="US-500", createdAt="2026-06-01"), ship, {50: "2026-07-01"},
        gitResolver=None, today="2026-07-13",
    )
    assert changed is True
    assert story["createdAt"] == "2026-06-01"  # preserved
    assert story["updatedAt"] == "2026-07-01"  # filled


# ---------------------------------------------------------------------------
# backfillBacklog + idempotency
# ---------------------------------------------------------------------------

def _miniBacklog():
    return {
        "schemaVersion": "2.0.0",
        "epics": [{"id": "E-1", "title": "E", "description": "d", "status": "active",
                   "createdAt": "2026-07-01", "updatedAt": "2026-07-01"}],
        "features": [{"id": "F-1", "parent": "E-1", "title": "F", "description": "d",
                      "status": "active", "createdAt": "2026-07-01", "updatedAt": "2026-07-01"}],
        "stories": [
            _drifted(id="US-500"),                       # shipped -> complete
            _drifted(id="US-446", status="pending"),     # open -> pending preserved
            _story(id="US-999"),                         # already compliant
        ],
    }


def _archiveFor(tmp_path):
    _writeArchive(tmp_path, "sprint.archive.2026-07-01_105741Z.json", 50,
                  [{"id": "US-500", "passes": True}])
    return tmp_path


def test_backfillBacklog_makesEveryStoryCompliantAndSchemaValid(tmp_path):
    data = _miniBacklog()
    result, changes = bf.backfillBacklog(data, _archiveFor(tmp_path), today="2026-07-13")
    for s in result["stories"]:
        assert bf.isCompliant(s) is True
    # validates against the real schema (goal of the whole story)
    validateBacklog(result)
    assert len(changes) == 2  # US-500 + US-446 changed; US-999 was compliant


def test_backfillBacklog_isIdempotent(tmp_path):
    archive = _archiveFor(tmp_path)
    data = _miniBacklog()
    result, first = bf.backfillBacklog(data, archive, today="2026-07-13")
    assert len(first) == 2
    result2, second = bf.backfillBacklog(result, archive, today="2026-07-13")
    assert second == []  # re-run is a no-op
    assert result2 == result


def test_backfillBacklog_openStoryNeverGuessedComplete(tmp_path):
    data = _miniBacklog()
    result, _ = bf.backfillBacklog(data, _archiveFor(tmp_path), today="2026-07-13")
    us446 = next(s for s in result["stories"] if s["id"] == "US-446")
    assert us446["status"] == "pending"  # NOT complete -- genuinely open
