################################################################################
# File Name: test_pm_tools_refuse_unknown_schema.py
# Purpose/Description: US-775 (F-137) -- every legacy tools/pm backlog reader
#                      refuses a schemaVersion it was not written for, instead
#                      of rendering it through a fallthrough. pm_status once
#                      printed the full ralphV2 backlog as EMPTY and exited 0.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-09-15
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-09-15    | Rex (US-775) | Initial -- behavioural refusals per reader, the
#               |              | backlog_set write guard, and the static scan
#               |              | over tools/pm with its positive controls.
# ================================================================================
################################################################################

"""Legacy PM backlog tools refuse an unknown schemaVersion (US-775).

Two shapes carry the weight here.

1. BEHAVIOUR, per reader: a ralphV2 backlog is refused with a non-zero exit, a
   message naming the expected and the found version, and the file's BYTES
   unchanged. Every value outside the vocabulary is tried, not only the one that
   bit us -- a ``!= "2.0.0"`` gate folds them all into one branch.
2. A STATIC SCAN over ``tools/pm``: any module that parses ``backlog.json`` must
   carry a schemaVersion assertion. Without it this story is one new reader away
   from recurring. Its detector has positive controls so it cannot pass inertly.
"""
from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from tools.pm import backlog_schema, backlog_set
from tools.pm._paths import REPO_ROOT

FIXTURES = REPO_ROOT / "tests" / "pm" / "fixtures"
TOOLS_PM = REPO_ROOT / "tools" / "pm"

# The live ralphV2 backlog's schemaVersion on 2026-09-15: the input pm_status
# rendered as an empty backlog.
RALPHV2_VERSION = "ralphv2-backlog/1.0"

# Every kind of value outside pm_status's vocabulary ('2.0.0' or absent):
# foreign formats, near-misses, and the right-looking value in the wrong type.
UNKNOWN_VERSIONS: list[Any] = [
    RALPHV2_VERSION, "1.0.0", "2.0", "2.0.0 ", "3.0.0", "", 2, 2.0, True, ["2.0.0"],
]

ABSENT = object()

ADD_STORY_ARGS = [
    "--add-story",
    "--story-parent", "F-137",
    "--story-title", "A tool that cannot read its input says so",
    "--story-goal", "As the PM, I want a refusal, not an empty backlog.",
    "--story-dod", "END STATE: the refusal names both versions.",
    "--story-vc", "run it against the ralphV2 backlog", "it refuses",
]

MUTATIONS = {
    "updated-by": ["--updated-by", "Marcus (PM)"],
    "feature-status": ["--feature", "F-137", "--status", "complete"],
    "add-story": ADD_STORY_ARGS,
}


# ---------------------------------------------------------------------------
# helpers + fixtures
# ---------------------------------------------------------------------------

def ralphV2Backlog() -> dict[str, Any]:
    """A small backlog in the live ralphV2 shape (top-level epics/features/stories)."""
    return {
        "schemaVersion": RALPHV2_VERSION,
        "updatedAt": "2026-09-15",
        "counters": {"epic": 1, "feature": 137, "story": 775},
        "epics": [{"id": "E-OPS", "title": "Operations", "description": "",
                   "createdAt": "2026-05-27", "updatedAt": "2026-05-27",
                   "status": "active"}],
        "features": [{"id": "F-137", "parent": "E-OPS", "title": "PM tooling",
                      "description": "", "createdAt": "2026-05-27",
                      "updatedAt": "2026-05-27", "status": "active"}],
        "stories": [{"id": "US-775", "parent": "F-137", "type": "tech-debt",
                     "size": "M", "status": "in_progress",
                     "title": "Legacy PM backlog tools must refuse an unknown schemaVersion",
                     "goal": "As the PM, I want a refusal."}],
    }


def v2Backlog() -> dict[str, Any]:
    return json.loads((FIXTURES / "v2_backlog_sample.json").read_text(encoding="utf-8"))


def setVersion(data: dict[str, Any], version: Any) -> dict[str, Any]:
    if version is ABSENT:
        data.pop("schemaVersion", None)
    else:
        data["schemaVersion"] = version
    return data


def writeJson(path: Path, data: Any) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refusalText(tool: str, expected: tuple[str | None, ...], found: Any) -> str:
    return str(backlog_schema.UnknownSchemaVersionError(tool, expected, found))


@pytest.fixture
def pmStatus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    """pm_status pointed at a throwaway share, with the git branch probe stubbed."""
    monkeypatch.setenv("FLEET_SHARE", str(tmp_path))
    module = importlib.import_module("tools.pm.pm_status")
    sprintPath = writeJson(tmp_path / "ralph" / "sprint.json", {
        "sprint": 87,
        "stories": [{"id": "US-775", "size": "M", "status": "in_progress", "title": "t"}],
    })
    counterPath = writeJson(tmp_path / "pm" / "story_counter.json",
                            {"nextId": 776, "lastUpdated": "2026-09-15"})
    monkeypatch.setattr(module, "SHARE_ROOT", tmp_path)
    monkeypatch.setattr(module, "BACKLOG_PATH", tmp_path / "pm" / "backlog.json")
    monkeypatch.setattr(module, "SPRINT_PATH", sprintPath)
    monkeypatch.setattr(module, "COUNTER_PATH", counterPath)
    monkeypatch.setattr(module, "printBranchSummary", lambda: None)
    return module


@pytest.fixture
def ralphV2Share(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A throwaway share whose live backlog is the ralphV2 format."""
    monkeypatch.setenv("FLEET_SHARE", str(tmp_path))
    writeJson(tmp_path / "pm" / "backlog.json", ralphV2Backlog())
    writeJson(tmp_path / "pm" / "story_counter.json",
              {"nextId": "US-776", "lastUpdated": "2026-09-15"})
    return tmp_path


# ---------------------------------------------------------------------------
# the shared assertion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("found", UNKNOWN_VERSIONS, ids=repr)
def test_assertSchemaVersion_everyValueOutsideTheVocabulary_isRefused(found: Any) -> None:
    with pytest.raises(backlog_schema.UnknownSchemaVersionError) as caught:
        backlog_schema.assertSchemaVersion({"schemaVersion": found}, "tool", ("2.0.0", None))
    assert caught.value.found == found
    assert "'2.0.0'" in str(caught.value)


def test_assertSchemaVersion_notAJsonObject_isRefused() -> None:
    with pytest.raises(backlog_schema.UnknownSchemaVersionError):
        backlog_schema.assertSchemaVersion([{"schemaVersion": "2.0.0"}], "tool")


def test_assertSchemaVersion_returnsTheVersionItRead() -> None:
    assert backlog_schema.assertSchemaVersion({"schemaVersion": "2.0.0"}, "tool") == "2.0.0"
    assert backlog_schema.assertSchemaVersion({}, "tool", ("2.0.0", None)) is None
    with pytest.raises(backlog_schema.UnknownSchemaVersionError):
        backlog_schema.assertSchemaVersion({}, "tool")


# ---------------------------------------------------------------------------
# pm_status -- the third branch
# ---------------------------------------------------------------------------

def test_pmStatus_ralphV2Backlog_exitsNonZeroNamingBothVersions_andPrintsNothing(
    pmStatus: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given: the live backlog is the ralphV2 format
    When: pm_status runs with no flags
    Then: non-zero exit, both versions named, and NO backlog printed -- it
          must never look like an empty backlog
    """
    path = writeJson(pmStatus.BACKLOG_PATH, ralphV2Backlog())
    before = digest(path)

    rc = pmStatus.main([])

    out, err = capsys.readouterr()
    assert rc == 2
    assert refusalText("pm_status", ("2.0.0", None), RALPHV2_VERSION) in err
    assert "'2.0.0'" in err and repr(RALPHV2_VERSION) in err
    assert out == ""
    assert digest(path) == before


@pytest.mark.parametrize("version", UNKNOWN_VERSIONS, ids=repr)
def test_pmStatus_everyUnknownVersion_isRefused_withoutATree(
    pmStatus: ModuleType, capsys: pytest.CaptureFixture[str], version: Any
) -> None:
    path = writeJson(pmStatus.BACKLOG_PATH, setVersion(v2Backlog(), version))
    before = digest(path)

    rc = pmStatus.main(["--backlog"])

    out, err = capsys.readouterr()
    assert rc == 2
    assert "unknown backlog schemaVersion" in err
    assert "BACKLOG" not in out
    assert digest(path) == before


def test_pmStatus_archivedV2Backlog_rendersTheFullSnapshot_andIsNotRewritten(
    pmStatus: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """
    Given: a 2.0.0 backlog at the archive path, read through --backlog-path
    When: pm_status runs
    Then: exit 0, every epic/feature/story is in the tree, and the archive's
          bytes are untouched (the override is read-only)
    """
    archived = tmp_path / "pm" / "archive" / "pre-ralphv2-20260914" / "backlog.legacy.json"
    archived.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json", archived)
    before = digest(archived)

    rc = pmStatus.main(["--backlog", "--backlog-path", str(archived)])

    out = capsys.readouterr().out
    assert rc == 0
    assert "=== BACKLOG v2.0.0 ===" in out
    snapshot = v2Backlog()
    for record in [*snapshot["epics"], *snapshot["features"], *snapshot["stories"]]:
        assert record["id"] in out
    assert digest(archived) == before


def test_pmStatus_refusalKeysOnTheSchema_notOnThePath(
    pmStatus: ModuleType, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The archive path does not grant a pass, and the live path does not force a refusal."""
    archived = writeJson(tmp_path / "pm" / "archive" / "backlog.legacy.json", ralphV2Backlog())
    writeJson(pmStatus.BACKLOG_PATH, v2Backlog())

    assert pmStatus.main(["--backlog", "--backlog-path", str(archived)]) == 2
    assert pmStatus.main(["--backlog"]) == 0
    assert "=== BACKLOG v2.0.0 ===" in capsys.readouterr().out


def test_pmStatus_unversionedV1Layout_stillRendersTheLegacyBacklog(
    pmStatus: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    shutil.copy(FIXTURES / "v1_backlog_sample.json", pmStatus.BACKLOG_PATH)

    rc = pmStatus.main(["--backlog"])

    assert rc == 0
    assert "B-103" in capsys.readouterr().out


def test_pmStatus_unknownBacklog_sprintOnlyStillRuns(
    pmStatus: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    """--sprint never reads story data from the backlog, so it is not refused."""
    writeJson(pmStatus.BACKLOG_PATH, ralphV2Backlog())

    rc = pmStatus.main(["--sprint"])

    out, err = capsys.readouterr()
    assert rc == 0
    assert "=== SPRINT: 87 ===" in out
    assert "BACKLOG" not in out
    assert "unknown backlog schemaVersion" in err


# ---------------------------------------------------------------------------
# backlog_set -- the read guard
# ---------------------------------------------------------------------------

def test_backlogSet_help_describesTheRefusal(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as exited:
        backlog_set.main(["--help"])

    assert exited.value.code == 0
    assert "schemaVersion" in capsys.readouterr().out


@pytest.mark.parametrize("argv", list(MUTATIONS.values()), ids=list(MUTATIONS))
def test_backlogSet_mutationOnARalphV2Backlog_isRefused_andTheFileIsUnmodified(
    ralphV2Share: Path, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    backlogPath = ralphV2Share / "pm" / "backlog.json"
    counterPath = ralphV2Share / "pm" / "story_counter.json"
    before = (digest(backlogPath), digest(counterPath))

    rc = backlog_set.main(argv)

    err = capsys.readouterr().err
    assert rc == 2
    assert "unknown backlog schemaVersion" in err
    assert "'2.0.0'" in err and repr(RALPHV2_VERSION) in err
    assert (digest(backlogPath), digest(counterPath)) == before
    assert list((ralphV2Share / "pm").glob("*.tmp")) == []


def test_pmStatusAndBacklogSet_refuseWithTheSameTypedMessage(
    pmStatus: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    writeJson(pmStatus.BACKLOG_PATH, ralphV2Backlog())

    assert pmStatus.main([]) == 2
    pmErr = capsys.readouterr().err
    assert backlog_set.main(["--backlog", str(pmStatus.BACKLOG_PATH), "--updated-by", "x"]) == 2
    setErr = capsys.readouterr().err

    expected = ("2.0.0", None)
    assert refusalText("pm_status", expected, RALPHV2_VERSION) in pmErr
    assert refusalText("backlog_set", expected, RALPHV2_VERSION) in setErr


@pytest.mark.parametrize("version", [*UNKNOWN_VERSIONS, ABSENT], ids=repr)
def test_backlogSet_addStory_refusesEveryVersionButTwoPointOh(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, version: Any
) -> None:
    monkeypatch.setenv("FLEET_SHARE", str(tmp_path))
    backlogPath = writeJson(tmp_path / "pm" / "backlog.json", setVersion(v2Backlog(), version))
    writeJson(tmp_path / "pm" / "story_counter.json", {"nextId": "US-361"})
    before = digest(backlogPath)
    argv = [*ADD_STORY_ARGS]
    argv[argv.index("F-137")] = "F-103"

    assert backlog_set.main(argv) == 2
    assert digest(backlogPath) == before


def test_addStory_calledDirectlyOnARalphV2Backlog_raisesTheTypedRefusal() -> None:
    data = ralphV2Backlog()

    with pytest.raises(backlog_schema.UnknownSchemaVersionError):
        backlog_set.addStory(
            data, {}, parent="F-137", title="t", goal="g",
            definitionOfDone=["d"], validationCriteria=[{"action": "a", "outcome": "o"}],
        )
    assert data == ralphV2Backlog()


# ---------------------------------------------------------------------------
# backlog_set -- the write guard
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    ("onDisk", "writing"),
    [("2.0.0", RALPHV2_VERSION), ("2.0.0", ABSENT), (ABSENT, "2.0.0"),
     (RALPHV2_VERSION, "2.0.0"), ("2.0.0", 2)],
    ids=["v2->ralphV2", "v2->absent", "absent->v2", "ralphV2->v2", "v2->int"],
)
def test_saveBacklog_neverWritesASchemaVersionThatDiffersFromTheOneItRead(
    tmp_path: Path, onDisk: Any, writing: Any
) -> None:
    path = writeJson(tmp_path / "backlog.json", setVersion(v2Backlog(), onDisk))
    before = digest(path)
    mutated = setVersion(json.loads(path.read_text(encoding="utf-8")), writing)

    with pytest.raises(backlog_set.SchemaVersionChangedError, match="schemaVersion"):
        backlog_set.saveBacklog(mutated, path)

    assert digest(path) == before
    assert list(tmp_path.glob("*.tmp")) == []


def test_addStory_onA2Point0Backlog_landsTheVersionItRead(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FLEET_SHARE", str(tmp_path))
    backlogPath = writeJson(tmp_path / "pm" / "backlog.json", v2Backlog())
    writeJson(tmp_path / "pm" / "story_counter.json", {"nextId": "US-361"})
    argv = [*ADD_STORY_ARGS]
    argv[argv.index("F-137")] = "F-103"

    assert backlog_set.main(argv) == 0

    assert json.loads(backlogPath.read_text(encoding="utf-8"))["schemaVersion"] == "2.0.0"


def test_updatedBy_onTheUnversionedV1Layout_landsWithoutStampingAVersion(tmp_path: Path) -> None:
    backlogPath = tmp_path / "backlog.json"
    shutil.copy(FIXTURES / "v1_backlog_sample.json", backlogPath)

    assert backlog_set.main(["--backlog", str(backlogPath), "--updated-by", "Marcus (PM)"]) == 0

    written = json.loads(backlogPath.read_text(encoding="utf-8"))
    assert "schemaVersion" not in written
    assert written["updatedBy"] == "Marcus (PM)"


# ---------------------------------------------------------------------------
# the other tools/pm story-data readers
# ---------------------------------------------------------------------------

def test_graduateStory_ralphV2Backlog_refusesAndWritesNothing(ralphV2Share: Path) -> None:
    module = importlib.import_module("tools.pm.graduate_story")
    backlogPath = ralphV2Share / "pm" / "backlog.json"
    before = digest(backlogPath)

    with pytest.raises(backlog_schema.UnknownSchemaVersionError):
        module.graduateStory("US-775", shareRoot=ralphV2Share, dryRun=False)

    assert digest(backlogPath) == before


def test_prdToSprint_ralphV2Backlog_refusesAndWritesNoSprint(ralphV2Share: Path) -> None:
    module = importlib.import_module("tools.pm.prd_to_sprint")
    prdPath = ralphV2Share / "pm" / "prds" / "prd-sample.md"
    prdPath.parent.mkdir(parents=True)
    shutil.copy(FIXTURES / "prd_sample.md", prdPath)
    outPath = ralphV2Share / "ralph" / "sprint.json"

    with pytest.raises(backlog_schema.UnknownSchemaVersionError):
        module.convertPrdToSprint(prdPath, outPath, shareRoot=ralphV2Share)

    assert not outPath.exists()


def test_backfillStoryMetadata_ralphV2Backlog_refusesAndWritesNothing(
    ralphV2Share: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = importlib.import_module("tools.pm.backfill_story_metadata")
    backlogPath = ralphV2Share / "pm" / "backlog.json"
    before = digest(backlogPath)

    rc = module.main(["--backlog", str(backlogPath)])

    assert rc == 2
    assert "unknown backlog schemaVersion" in capsys.readouterr().err
    assert digest(backlogPath) == before


# ---------------------------------------------------------------------------
# the static scan (acceptance #3)
# ---------------------------------------------------------------------------

# A v1 reader BY DESIGN: its whole job is to read the pre-2.0.0 layout.
EXEMPT_READERS = {"migrate_backlog_v1_to_v2.py"}

# The assertions that genuinely refuse: the shared one, and the lint's
# collect-all validator whose first rule is the schemaVersion hard stop.
_SCHEMA_ASSERTIONS = ("assertSchemaVersion(", "collectBacklogViolations(")
_PARSES_JSON = re.compile(r"\bjson\.loads?\(")

# The readers that exist today. The scan must find at least these, or it has
# gone blind rather than green.
KNOWN_READERS = {
    "pm_status.py", "backlog_set.py", "graduate_story.py", "prd_to_sprint.py",
    "backfill_story_metadata.py", "sprint_lint.py",
}


def readsBacklogStoryData(source: str) -> bool:
    return "backlog.json" in source and _PARSES_JSON.search(source) is not None


def assertsSchemaVersion(source: str) -> bool:
    return any(token in source for token in _SCHEMA_ASSERTIONS)


def backlogReaders() -> dict[str, str]:
    return {
        path.name: source
        for path in sorted(TOOLS_PM.glob("*.py"))
        if readsBacklogStoryData(source := path.read_text(encoding="utf-8"))
    }


def test_everyBacklogReaderInToolsPm_assertsTheSchemaVersion() -> None:
    offenders = [
        name for name, source in backlogReaders().items()
        if name not in EXEMPT_READERS and not assertsSchemaVersion(source)
    ]
    assert offenders == [], (
        f"these tools/pm modules parse backlog.json with no schemaVersion "
        f"assertion: {offenders}. Call backlog_schema.assertSchemaVersion on the "
        f"parsed data before reading story fields."
    )


def test_theScanFindsEveryKnownReader_andTheExemptionIsLive() -> None:
    readers = set(backlogReaders())
    assert KNOWN_READERS <= readers
    assert EXEMPT_READERS <= readers, "an exemption for a module that no longer reads the backlog"


def test_detector_flagsABareReader_andClearsAnAssertedOne() -> None:
    bare = 'data = json.loads(Path("backlog.json").read_text())\n'
    assert readsBacklogStoryData(bare)
    assert not assertsSchemaVersion(bare)
    assert assertsSchemaVersion(bare + 'assertSchemaVersion(data, "tool")\n')
    assert not readsBacklogStoryData("# backlog.json named in a comment, never parsed\n")
