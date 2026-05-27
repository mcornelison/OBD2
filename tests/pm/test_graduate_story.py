"""Tests for graduate_story -- move completed items to archive."""
import json
import shutil
from pathlib import Path
import pytest

from offices.pm.scripts.graduate_story import graduateStory

FIXTURES = Path(__file__).parent / "fixtures"


def test_graduateStory_movesMdAndUpdatesBacklog(tmp_path):
    (tmp_path / "offices/pm/backlog").mkdir(parents=True)
    (tmp_path / "offices/pm/archive/completed-work-products").mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json", tmp_path / "offices/pm/backlog.json")
    storyMdPath = tmp_path / "offices/pm/backlog/US-359-test.md"
    storyMdPath.write_text("---\nid: US-359\nstatus: complete\n---\n# US-359\n", encoding="utf-8")

    # mark story complete in backlog.json
    backlogPath = tmp_path / "offices/pm/backlog.json"
    data = json.loads(backlogPath.read_text())
    data["stories"][0]["status"] = "complete"
    backlogPath.write_text(json.dumps(data, indent=2), encoding="utf-8")

    graduateStory("US-359", repoRoot=tmp_path, dryRun=False)

    # MD moved
    assert not storyMdPath.exists()
    assert (tmp_path / "offices/pm/archive/completed-work-products/US-359-test.md").exists()
    # JSON entry removed
    data = json.loads(backlogPath.read_text())
    assert all(s["id"] != "US-359" for s in data["stories"])


def test_graduateStory_storyNotComplete_raises(tmp_path):
    (tmp_path / "offices/pm/backlog").mkdir(parents=True)
    shutil.copy(FIXTURES / "v2_backlog_sample.json", tmp_path / "offices/pm/backlog.json")
    (tmp_path / "offices/pm/backlog/US-359-test.md").write_text(
        "---\nid: US-359\n---\n# t\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="not complete"):
        graduateStory("US-359", repoRoot=tmp_path, dryRun=False)
