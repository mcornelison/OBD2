################################################################################
# File Name: test_release_versioning.py
# Purpose/Description: Unit + integration tests for US-241 deploy versioning.
#                      Covers scripts/version_helpers.py (parseVersion,
#                      bumpVersion, validateRelease, readDeployVersion,
#                      composeReleaseRecord), the CLI subcommands the deploy
#                      scripts shell out to, deploy/RELEASE_VERSION shape, and
#                      deploy-pi.sh / deploy-server.sh --dry-run version-write
#                      step output.
# Author: Rex (Ralph Agent)
# Creation Date: 2026-04-30
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-04-30    | Rex          | Initial implementation (Sprint 19 US-241)
# 2026-05-03    | Rex          | US-272: add test_releaseVersionFile_holdsValidSemver
#                              | (TD-040 closure follow-up; original literal-V0.18.0
#                              | assertion deleted in commit 57bdda6 2026-04-30; this
#                              | adds the spec-required shape-not-literal regex +
#                              | non-empty-description gate, mirroring US-269/TD-044)
# ================================================================================
################################################################################

"""Tests for US-241 release versioning + deploy records.

The deploy scripts compose the JSON release record by shelling out to
scripts/version_helpers.py compose-record (so the JSON shape is owned by one
testable Python module, not duplicated in two bash heredocs). These tests
exercise the helpers directly AND drive the deploy scripts in --dry-run mode
to confirm the version-write step would emit a valid record.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
HELPERS_PATH = REPO_ROOT / "scripts" / "version_helpers.py"
RELEASE_VERSION_PATH = REPO_ROOT / "deploy" / "RELEASE_VERSION"
DEPLOY_PI = REPO_ROOT / "deploy" / "deploy-pi.sh"
DEPLOY_SERVER = REPO_ROOT / "deploy" / "deploy-server.sh"


def _loadHelpers():
    """Import scripts/version_helpers.py without polluting sys.path globally."""
    spec = spec_from_file_location("version_helpers", HELPERS_PATH)
    assert spec and spec.loader, f"cannot import {HELPERS_PATH}"
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _bashAvailable() -> bool:
    return shutil.which("bash") is not None


# ---- parseVersion ---------------------------------------------------------

class TestParseVersion:
    def test_parseVersion_v0_18_0_returnsTriple(self):
        m = _loadHelpers()
        assert m.parseVersion("V0.18.0") == (0, 18, 0)

    def test_parseVersion_v1_2_3_returnsTriple(self):
        m = _loadHelpers()
        assert m.parseVersion("V1.2.3") == (1, 2, 3)

    def test_parseVersion_v0_0_0_returnsTriple(self):
        m = _loadHelpers()
        assert m.parseVersion("V0.0.0") == (0, 0, 0)

    def test_parseVersion_lowercaseV_raises(self):
        m = _loadHelpers()
        with pytest.raises(ValueError, match="capital V"):
            m.parseVersion("v0.18.0")

    def test_parseVersion_missingPrefix_raises(self):
        m = _loadHelpers()
        with pytest.raises(ValueError):
            m.parseVersion("0.18.0")

    def test_parseVersion_twoParts_raises(self):
        m = _loadHelpers()
        with pytest.raises(ValueError):
            m.parseVersion("V0.18")

    def test_parseVersion_fourParts_raises(self):
        m = _loadHelpers()
        with pytest.raises(ValueError):
            m.parseVersion("V0.18.0.1")

    def test_parseVersion_nonNumeric_raises(self):
        m = _loadHelpers()
        with pytest.raises(ValueError):
            m.parseVersion("V0.beta.0")


# ---- bumpVersion ----------------------------------------------------------

class TestBumpVersion:
    def test_bumpVersion_minor_incrementsMinorResetsPatch(self):
        m = _loadHelpers()
        assert m.bumpVersion("V0.18.0", "minor") == "V0.19.0"

    def test_bumpVersion_minor_resetsPatchToZero(self):
        m = _loadHelpers()
        assert m.bumpVersion("V0.18.5", "minor") == "V0.19.0"

    def test_bumpVersion_major_incrementsMajorResetsMinorPatch(self):
        m = _loadHelpers()
        assert m.bumpVersion("V0.18.0", "major") == "V1.0.0"

    def test_bumpVersion_major_fromV1ResetsBoth(self):
        m = _loadHelpers()
        assert m.bumpVersion("V1.5.7", "major") == "V2.0.0"

    def test_bumpVersion_patch_incrementsPatchOnly(self):
        m = _loadHelpers()
        assert m.bumpVersion("V0.18.0", "patch") == "V0.18.1"

    def test_bumpVersion_patch_increments(self):
        m = _loadHelpers()
        assert m.bumpVersion("V1.2.3", "patch") == "V1.2.4"

    def test_bumpVersion_unknownKind_raises(self):
        m = _loadHelpers()
        with pytest.raises(ValueError, match="kind"):
            m.bumpVersion("V0.18.0", "build")

    def test_bumpVersion_invalidVersion_raises(self):
        m = _loadHelpers()
        with pytest.raises(ValueError):
            m.bumpVersion("not-a-version", "patch")


# ---- validateRelease ------------------------------------------------------

class TestValidateRelease:
    def _good(self) -> dict:
        return {
            "version": "V0.18.0",
            "releasedAt": "2026-04-30T14:32:00Z",
            "gitHash": "abc1234",
            "theme": "Ops Hardening",
            "description": "Sprint 18 shipped",
        }

    def test_validateRelease_goodRecord_returnsTrue(self):
        m = _loadHelpers()
        assert m.validateRelease(self._good()) is True

    def test_validateRelease_missingVersion_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        del rec["version"]
        assert m.validateRelease(rec) is False

    def test_validateRelease_missingReleasedAt_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        del rec["releasedAt"]
        assert m.validateRelease(rec) is False

    def test_validateRelease_missingGitHash_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        del rec["gitHash"]
        assert m.validateRelease(rec) is False

    def test_validateRelease_missingDescription_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        del rec["description"]
        assert m.validateRelease(rec) is False

    def test_validateRelease_descriptionAt400_returnsTrue(self):
        m = _loadHelpers()
        rec = self._good()
        rec["description"] = "x" * 400
        assert m.validateRelease(rec) is True

    def test_validateRelease_descriptionAt401_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["description"] = "x" * 401
        assert m.validateRelease(rec) is False

    def test_validateRelease_missingTheme_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        del rec["theme"]
        assert m.validateRelease(rec) is False

    def test_validateRelease_emptyTheme_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["theme"] = ""
        assert m.validateRelease(rec) is False

    def test_validateRelease_themeAt50_returnsTrue(self):
        m = _loadHelpers()
        rec = self._good()
        rec["theme"] = "x" * 50
        assert m.validateRelease(rec) is True

    def test_validateRelease_themeAt51_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["theme"] = "x" * 51
        assert m.validateRelease(rec) is False

    def test_validateRelease_invalidVersion_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["version"] = "1.0.0"
        assert m.validateRelease(rec) is False

    def test_validateRelease_lowercaseVPrefix_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["version"] = "v0.18.0"
        assert m.validateRelease(rec) is False

    def test_validateRelease_releasedAtNoZSuffix_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["releasedAt"] = "2026-04-30T14:32:00"
        assert m.validateRelease(rec) is False

    def test_validateRelease_releasedAtSpaceSeparator_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["releasedAt"] = "2026-04-30 14:32:00Z"
        assert m.validateRelease(rec) is False

    def test_validateRelease_emptyGitHash_returnsFalse(self):
        m = _loadHelpers()
        rec = self._good()
        rec["gitHash"] = ""
        assert m.validateRelease(rec) is False

    def test_validateRelease_nonDictInput_returnsFalse(self):
        m = _loadHelpers()
        assert m.validateRelease(None) is False
        assert m.validateRelease("not-a-record") is False
        assert m.validateRelease([]) is False


# ---- readDeployVersion ----------------------------------------------------

class TestReadDeployVersion:
    def test_readDeployVersion_validJsonFile_returnsRecord(self, tmp_path):
        m = _loadHelpers()
        f = tmp_path / ".deploy-version"
        good = {
            "version": "V0.18.0",
            "releasedAt": "2026-04-30T14:32:00Z",
            "gitHash": "abc1234",
            "theme": "Ops Hardening",
            "description": "Sprint 18",
        }
        f.write_text(json.dumps(good))
        assert m.readDeployVersion(f) == good

    def test_readDeployVersion_missingFile_returnsNone(self, tmp_path):
        m = _loadHelpers()
        assert m.readDeployVersion(tmp_path / "nonexistent") is None

    def test_readDeployVersion_malformedJson_returnsNone(self, tmp_path):
        m = _loadHelpers()
        f = tmp_path / ".deploy-version"
        f.write_text("{not-json")
        assert m.readDeployVersion(f) is None

    def test_readDeployVersion_invalidShape_returnsNone(self, tmp_path):
        m = _loadHelpers()
        f = tmp_path / ".deploy-version"
        f.write_text(json.dumps({"version": "V0.18.0"}))
        assert m.readDeployVersion(f) is None


# ---- composeReleaseRecord -------------------------------------------------

class TestComposeReleaseRecord:
    def test_composeReleaseRecord_shape(self, tmp_path):
        m = _loadHelpers()
        vf = tmp_path / "RELEASE_VERSION"
        vf.write_text(json.dumps({
            "version": "V0.18.0", "theme": "Ops Hardening", "description": "Test"
        }))
        rec = m.composeReleaseRecord(
            vf, gitHash="abc1234", releasedAt="2026-04-30T14:32:00Z"
        )
        assert rec == {
            "version": "V0.18.0",
            "releasedAt": "2026-04-30T14:32:00Z",
            "gitHash": "abc1234",
            "theme": "Ops Hardening",
            "description": "Test",
        }
        assert m.validateRelease(rec) is True

    def test_composeReleaseRecord_autoTimestampIsUtcZ(self, tmp_path):
        m = _loadHelpers()
        vf = tmp_path / "RELEASE_VERSION"
        vf.write_text(json.dumps({
            "version": "V0.18.0", "theme": "Ops Hardening", "description": "Test"
        }))
        rec = m.composeReleaseRecord(vf, gitHash="abc1234")
        assert rec["releasedAt"].endswith("Z")
        assert "T" in rec["releasedAt"]
        assert m.validateRelease(rec) is True

    def test_composeReleaseRecord_missingVersionFile_raises(self, tmp_path):
        m = _loadHelpers()
        with pytest.raises(FileNotFoundError):
            m.composeReleaseRecord(
                tmp_path / "NOPE", gitHash="abc1234", releasedAt="2026-04-30T14:32:00Z"
            )

    def test_composeReleaseRecord_descriptionTooLong_raises(self, tmp_path):
        m = _loadHelpers()
        vf = tmp_path / "RELEASE_VERSION"
        vf.write_text(json.dumps({
            "version": "V0.18.0", "theme": "Ops Hardening", "description": "x" * 401
        }))
        with pytest.raises(ValueError, match="description"):
            m.composeReleaseRecord(
                vf, gitHash="abc1234", releasedAt="2026-04-30T14:32:00Z"
            )

    def test_composeReleaseRecord_themeMissing_raises(self, tmp_path):
        m = _loadHelpers()
        vf = tmp_path / "RELEASE_VERSION"
        vf.write_text(json.dumps({"version": "V0.18.0", "description": "Test"}))
        with pytest.raises(ValueError, match="theme"):
            m.composeReleaseRecord(
                vf, gitHash="abc1234", releasedAt="2026-04-30T14:32:00Z"
            )

    def test_composeReleaseRecord_themeTooLong_raises(self, tmp_path):
        m = _loadHelpers()
        vf = tmp_path / "RELEASE_VERSION"
        vf.write_text(json.dumps({
            "version": "V0.18.0", "theme": "x" * 51, "description": "Test"
        }))
        with pytest.raises(ValueError, match="theme"):
            m.composeReleaseRecord(
                vf, gitHash="abc1234", releasedAt="2026-04-30T14:32:00Z"
            )

    def test_composeReleaseRecord_invalidVersionInFile_raises(self, tmp_path):
        m = _loadHelpers()
        vf = tmp_path / "RELEASE_VERSION"
        vf.write_text(json.dumps({
            "version": "1.0.0", "theme": "Ops Hardening", "description": "Test"
        }))
        with pytest.raises(ValueError):
            m.composeReleaseRecord(
                vf, gitHash="abc1234", releasedAt="2026-04-30T14:32:00Z"
            )


# ---- canonical RELEASE_VERSION file --------------------------------------

class TestReleaseVersionFile:
    def test_releaseVersionFile_existsAtRepoRoot(self):
        assert RELEASE_VERSION_PATH.is_file(), (
            f"deploy/RELEASE_VERSION must exist (US-241): {RELEASE_VERSION_PATH}"
        )

    def test_releaseVersionFile_isValidJsonWithRequiredKeys(self):
        data = json.loads(RELEASE_VERSION_PATH.read_text())
        assert "version" in data
        assert "theme" in data
        assert "description" in data

    def test_releaseVersionFile_versionParses(self):
        m = _loadHelpers()
        data = json.loads(RELEASE_VERSION_PATH.read_text())
        m.parseVersion(data["version"])

    def test_releaseVersionFile_holdsValidSemver(self):
        # TD-040: shape-not-literal gate.  Mirrors US-269's TD-044 closure pattern
        # (test_migration_0005_dtc_log.py::test_appendedAtEnd).  The original
        # `seedVersionIsV0_18_0` literal assertion broke on every PM sprint-close
        # version bump per feedback_pm_sprint_close_version_bump.md and was
        # deleted in commit 57bdda6 (2026-04-30).  This regex+non-empty-description
        # check is stable across all future bumps and catches both bug classes:
        # (a) RELEASE_VERSION malformed (regex fails) and (b) description blank
        # (len-zero fails).  parseVersion-via-test_releaseVersionFile_versionParses
        # provides the canonical shape gate; this test is the explicit shape+
        # non-empty pair the Sprint 23 spec calls for.
        data = json.loads(RELEASE_VERSION_PATH.read_text())
        assert re.match(r"^V\d+\.\d+\.\d+$", data["version"]) is not None, (
            f"RELEASE_VERSION version field must match V<major>.<minor>.<patch>: "
            f"got {data['version']!r}"
        )
        assert len(data["description"]) > 0, (
            "RELEASE_VERSION description field must be non-empty"
        )

    def test_releaseVersionFile_themeWithin50Char(self):
        data = json.loads(RELEASE_VERSION_PATH.read_text())
        assert 0 < len(data["theme"]) <= 50

    def test_releaseVersionFile_descriptionWithin400Char(self):
        data = json.loads(RELEASE_VERSION_PATH.read_text())
        assert len(data["description"]) <= 400


# ---- CLI: compose-record subcommand ---------------------------------------

class TestComposeRecordCli:
    def test_composeRecordCli_emitsValidJsonRecord(self, tmp_path):
        m = _loadHelpers()
        vf = tmp_path / "RELEASE_VERSION"
        vf.write_text(json.dumps({
            "version": "V0.18.0", "theme": "Ops Hardening", "description": "Test"
        }))
        result = subprocess.run(
            [
                sys.executable,
                str(HELPERS_PATH),
                "compose-record",
                "--version-file",
                str(vf),
                "--git-hash",
                "abc1234",
                "--released-at",
                "2026-04-30T14:32:00Z",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode == 0, result.stderr
        rec = json.loads(result.stdout.strip())
        assert rec["version"] == "V0.18.0"
        assert rec["releasedAt"] == "2026-04-30T14:32:00Z"
        assert rec["gitHash"] == "abc1234"
        assert rec["theme"] == "Ops Hardening"
        assert rec["description"] == "Test"
        assert m.validateRelease(rec) is True

    def test_composeRecordCli_invalidVersionFile_exitsNonZero(self, tmp_path):
        result = subprocess.run(
            [
                sys.executable,
                str(HELPERS_PATH),
                "compose-record",
                "--version-file",
                str(tmp_path / "missing"),
                "--git-hash",
                "abc1234",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        assert result.returncode != 0


# ---- deploy-pi.sh + deploy-server.sh dry-run version-write step -----------

@pytest.mark.skipif(not _bashAvailable(), reason="bash not available")
class TestDeployScriptDryRun:
    def test_deployPiSh_dryRun_includesVersionWriteStep(self):
        result = subprocess.run(
            ["bash", str(DEPLOY_PI), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert ".deploy-version" in out, (
            "deploy-pi.sh --dry-run must show the version-write step path"
        )

    def test_deployPiSh_dryRun_jsonShapeValid(self):
        """Extract the JSON the dry-run prints and validate via validateRelease."""
        result = subprocess.run(
            ["bash", str(DEPLOY_PI), "--dry-run"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        m = _loadHelpers()
        rec = _extractDeployVersionJson(result.stdout)
        assert rec is not None, (
            f"dry-run output had no .deploy-version JSON line:\n{result.stdout}"
        )
        assert m.validateRelease(rec) is True, (
            f"composed record fails validateRelease: {rec}"
        )

    def test_deployServerSh_dryRun_isUnsupportedOrIncludesVersionStep(self):
        """deploy-server.sh has no --dry-run; this asserts the version path
        appears in the script body so the version-write step is wired in."""
        body = DEPLOY_SERVER.read_text()
        assert ".deploy-version" in body, (
            "deploy-server.sh must include the .deploy-version write step"
        )


def _extractDeployVersionJson(output: str) -> dict | None:
    """Find the JSON record the deploy-pi.sh dry-run line emits.

    The version-write step prints:
        DRY-RUN would write to <path>/.deploy-version: {"version": "V...", ...}
    """
    for line in output.splitlines():
        if ".deploy-version:" not in line:
            continue
        idx = line.find("{")
        if idx == -1:
            continue
        try:
            return json.loads(line[idx:])
        except json.JSONDecodeError:
            continue
    return None
