################################################################################
# File Name: test_chain_validate_aggregate.py
# Purpose/Description: TDD coverage for the US-318 / B-067 chain_validate_aggregate.py
#     script -- enumerates sprint.json files in a V0.X chain, filters by
#     validation.currentVersion prefix, aggregates validatesFeatures + bigDoD,
#     and detects unvalidated sprints (chainStatus = INCOMPLETE) vs fully
#     validated chains (chainStatus = READY).
#
# Author: Rex (Ralph agent)
# Creation Date: 2026-05-10
# Copyright: (c) 2026 Eclipse OBD-II Project. All rights reserved.
#
# Modification History:
# ================================================================================
# Date          | Author       | Description
# ================================================================================
# 2026-05-10    | Rex (US-318) | Initial -- synthetic chain coverage for the
#               |              | /chain-validated slash command's aggregate
#               |              | support script.  Would FAIL pre-fix because
#               |              | chain_validate_aggregate.py does not exist on
#               |              | the pre-fix repo surface (ModuleNotFoundError
#               |              | on importlib load).
# ================================================================================
################################################################################

"""TDD tests for US-318: chain_validate_aggregate.py.

Six tests covering the synthetic-chain happy path + incomplete-chain detection
+ CLI surface.  All would FAIL pre-fix because the script does not exist.

Tests mock a synthetic test-branch chain by writing temporary sprint.json
files to ``tmp_path`` and passing explicit ``--paths`` to the script.  Real
usage globs ``offices/ralph/archive/sprint.archive.*.json`` + ``sprint.json``
filtered by ``validation.currentVersion`` prefix (e.g. ``V0.27``); the same
``aggregateChain`` function backs both code paths.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _PROJECT_ROOT / "offices" / "pm" / "scripts" / "chain_validate_aggregate.py"
_BUMP_SCRIPT_PATH = _PROJECT_ROOT / "offices" / "pm" / "scripts" / "chain_validate_manifest_bump.py"


def _loadAggregate():  # noqa: ANN202 -- test helper
    """Load offices/pm/scripts/chain_validate_aggregate.py as a module.

    Mirrors tests/pm/test_sprint_lint_filestotouch.py's pattern for loading
    a script that lives outside the importable ``src/`` tree.
    """
    spec = importlib.util.spec_from_file_location("chain_validate_aggregate", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, (
        f"chain_validate_aggregate.py not found at {_SCRIPT_PATH} -- US-318 ships this script"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["chain_validate_aggregate"] = mod
    spec.loader.exec_module(mod)
    return mod


def _loadBump():  # noqa: ANN202 -- test helper
    """Load offices/pm/scripts/chain_validate_manifest_bump.py as a module."""
    spec = importlib.util.spec_from_file_location("chain_validate_manifest_bump", _BUMP_SCRIPT_PATH)
    assert spec is not None and spec.loader is not None, (
        f"chain_validate_manifest_bump.py not found at {_BUMP_SCRIPT_PATH} -- US-318 ships this script"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["chain_validate_manifest_bump"] = mod
    spec.loader.exec_module(mod)
    return mod


def _writeManifest(path: Path, features: list[dict]) -> Path:
    """Write a minimal regression_manifest.json with the given feature records."""
    payload = {
        "manifestVersion": 1,
        "lastUpdated": "2026-05-10",
        "lastUpdatedBy": "test",
        "features": features,
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _writeSprintJson(
    path: Path,
    *,
    currentVersion: str,
    validatedAt: str | None,
    validatedBy: str | None,
    validatesFeatures: list[str],
    bigDoD: list[str] | None = None,
    sprintTitle: str = "Synthetic Sprint",
) -> Path:
    """Write a minimal sprint.json with just enough schema for aggregateChain."""
    payload = {
        "sprint": sprintTitle,
        "stories": [],
        "validation": {
            "bigDefinitionOfDone": bigDoD or [f"Clause for {currentVersion}"],
            "validationMethod": "real_engine_on_test",
            "validatesFeatures": validatesFeatures,
            "currentVersion": currentVersion,
            "validatedAt": validatedAt,
            "validatedBy": validatedBy,
        },
    }
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ================================================================================
# 1. aggregateChain() -- happy path: multi-sprint chain aggregates validatesFeatures
# ================================================================================


class TestAggregateChainHappyPath:
    """Three-sprint chain validates feature union + chainStatus = READY."""

    def test_aggregateChain_threeSprintChain_unionsValidatesFeatures(self, tmp_path: Path) -> None:
        """Given: 3 sprint.json files all at V0.99.x with non-null validatedAt
        + disjoint validatesFeatures.

        When: aggregateChain is called with all 3 paths.

        Then: aggregateValidatesFeatures is the sorted union; chainStatus = READY;
            unvalidatedSprints is empty.
        """
        mod = _loadAggregate()

        s1 = _writeSprintJson(
            tmp_path / "s1.json",
            currentVersion="V0.99.2",
            validatedAt="2026-06-01T00:00:00Z",
            validatedBy="Mike (CIO confirmed) + Drive 99",
            validatesFeatures=["F-001", "F-002"],
            bigDoD=["S1 clause A"],
        )
        s2 = _writeSprintJson(
            tmp_path / "s2.json",
            currentVersion="V0.99.3",
            validatedAt="2026-06-02T00:00:00Z",
            validatedBy="Mike (CIO confirmed) + Drain 99",
            validatesFeatures=["F-002", "F-003"],
            bigDoD=["S2 clause A", "S2 clause B"],
        )
        s3 = _writeSprintJson(
            tmp_path / "s3.json",
            currentVersion="V0.99.4",
            validatedAt="2026-06-03T00:00:00Z",
            validatedBy="Mike (CIO confirmed) + Drive 100",
            validatesFeatures=["F-004"],
            bigDoD=["S3 clause A"],
        )

        result = mod.aggregateChain([s1, s2, s3], chainPrefix="V0.99")

        assert result["chainPrefix"] == "V0.99"
        assert result["aggregateValidatesFeatures"] == ["F-001", "F-002", "F-003", "F-004"]
        assert result["chainStatus"] == "READY"
        assert result["unvalidatedSprints"] == []
        assert len(result["sprintsInChain"]) == 3
        # Ordered by currentVersion
        versions = [s["currentVersion"] for s in result["sprintsInChain"]]
        assert versions == ["V0.99.2", "V0.99.3", "V0.99.4"]
        # aggregateBigDoD preserves source + clauses across sprints
        assert len(result["aggregateBigDoD"]) == 4  # 1 + 2 + 1 clauses


# ================================================================================
# 2. aggregateChain() -- chain version prefix filtering
# ================================================================================


class TestAggregateChainPrefixFiltering:
    """Sprints whose currentVersion does not match chainPrefix are excluded."""

    def test_aggregateChain_chainPrefixFilter_excludesOffChainSprints(self, tmp_path: Path) -> None:
        """Given: 3 sprint.json files spanning two minor versions (V0.99.x + V0.98.x).

        When: aggregateChain is called with chainPrefix='V0.99'.

        Then: only the V0.99.x sprints contribute to aggregates; V0.98.x is filtered out.
        """
        mod = _loadAggregate()

        # In chain
        inChain1 = _writeSprintJson(
            tmp_path / "s1.json",
            currentVersion="V0.99.2",
            validatedAt="2026-06-01T00:00:00Z",
            validatedBy="Mike",
            validatesFeatures=["F-001"],
        )
        inChain2 = _writeSprintJson(
            tmp_path / "s2.json",
            currentVersion="V0.99.3",
            validatedAt="2026-06-02T00:00:00Z",
            validatedBy="Mike",
            validatesFeatures=["F-002"],
        )
        # Off chain (V0.98.x)
        offChain = _writeSprintJson(
            tmp_path / "off.json",
            currentVersion="V0.98.5",
            validatedAt="2026-05-15T00:00:00Z",
            validatedBy="Mike",
            validatesFeatures=["F-999"],
        )

        result = mod.aggregateChain([inChain1, inChain2, offChain], chainPrefix="V0.99")

        assert len(result["sprintsInChain"]) == 2
        assert result["aggregateValidatesFeatures"] == ["F-001", "F-002"]
        assert "F-999" not in result["aggregateValidatesFeatures"]


# ================================================================================
# 3. aggregateChain() -- INCOMPLETE detection (validatedAt missing)
# ================================================================================


class TestAggregateChainIncompleteDetection:
    """Any sprint with validatedAt=null flips chainStatus to INCOMPLETE.

    Real-world: detects the V0.27 chain pre-Drive-11+ where every sprint
    has validatedAt=null because the real-hardware drill has not yet run.
    """

    def test_aggregateChain_oneUnvalidatedSprint_setsChainStatusIncomplete(
        self, tmp_path: Path
    ) -> None:
        """Given: 2-sprint chain, one validated + one not.

        When: aggregateChain is called.

        Then: chainStatus = INCOMPLETE; unvalidatedSprints lists the missing one.
        """
        mod = _loadAggregate()

        validated = _writeSprintJson(
            tmp_path / "validated.json",
            currentVersion="V0.99.2",
            validatedAt="2026-06-01T00:00:00Z",
            validatedBy="Mike",
            validatesFeatures=["F-001"],
        )
        unvalidated = _writeSprintJson(
            tmp_path / "unvalidated.json",
            currentVersion="V0.99.3",
            validatedAt=None,
            validatedBy=None,
            validatesFeatures=["F-002"],
        )

        result = mod.aggregateChain([validated, unvalidated], chainPrefix="V0.99")

        assert result["chainStatus"] == "INCOMPLETE"
        assert result["unvalidatedSprints"] == ["V0.99.3"]
        # Features still aggregate even when chain is incomplete
        assert result["aggregateValidatesFeatures"] == ["F-001", "F-002"]


# ================================================================================
# 4. aggregateChain() -- empty chain (no sprints match prefix)
# ================================================================================


class TestAggregateChainEmpty:
    """Empty inputs return a well-formed empty aggregate (chainStatus=INCOMPLETE)."""

    def test_aggregateChain_noPaths_returnsEmptyAggregate(self, tmp_path: Path) -> None:
        """Given: empty path list.

        When: aggregateChain is called.

        Then: returns well-formed dict with empty aggregates + INCOMPLETE status
            (an empty chain cannot be 'READY' to merge to main).
        """
        mod = _loadAggregate()
        result = mod.aggregateChain([], chainPrefix="V0.99")

        assert result["chainPrefix"] == "V0.99"
        assert result["sprintsInChain"] == []
        assert result["aggregateValidatesFeatures"] == []
        assert result["aggregateBigDoD"] == []
        assert result["chainStatus"] == "INCOMPLETE"
        assert result["unvalidatedSprints"] == []


# ================================================================================
# 5. CLI surface -- --json emits machine-readable output
# ================================================================================


class TestCliJsonOutput:
    """End-to-end CLI invocation: --paths + --chain + --json produces parseable JSON."""

    def test_cli_jsonFlag_emitsParseableJson(self, tmp_path: Path) -> None:
        """Given: 1 synthetic sprint.json on disk.

        When: chain_validate_aggregate.py is invoked via subprocess with --json.

        Then: stdout is valid JSON containing the expected aggregate keys.
        """
        sprint = _writeSprintJson(
            tmp_path / "synthetic.json",
            currentVersion="V0.99.2",
            validatedAt="2026-06-01T00:00:00Z",
            validatedBy="Mike (CIO confirmed) + Drive 99",
            validatesFeatures=["F-001", "F-002"],
        )

        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--chain",
                "V0.99",
                "--paths",
                str(sprint),
                "--json",
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        # Exit code may be 0 (READY) or 1 (INCOMPLETE) -- either OK; we care
        # about the JSON shape, not the gate semantics.
        assert result.returncode in (0, 1), f"unexpected exit {result.returncode}: {result.stderr}"
        parsed = json.loads(result.stdout)
        assert parsed["chainPrefix"] == "V0.99"
        assert parsed["aggregateValidatesFeatures"] == ["F-001", "F-002"]
        assert parsed["chainStatus"] == "READY"


# ================================================================================
# 6. CLI exit code -- strict mode flags INCOMPLETE chain (CI gate)
# ================================================================================


class TestCliStrictExitCode:
    """--strict flag enforces chainStatus == READY (exit 1 if INCOMPLETE).

    Useful as the slash command's pre-flight gate before running phases that
    touch git history (merge to main).
    """

    def test_cli_strict_incompleteChain_exitsOne(self, tmp_path: Path) -> None:
        unvalidated = _writeSprintJson(
            tmp_path / "unvalidated.json",
            currentVersion="V0.99.5",
            validatedAt=None,
            validatedBy=None,
            validatesFeatures=["F-001"],
        )

        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--chain",
                "V0.99",
                "--paths",
                str(unvalidated),
                "--strict",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 1, (
            f"expected exit 1 (INCOMPLETE+strict), got {result.returncode}: {result.stdout}"
        )

    def test_cli_strict_readyChain_exitsZero(self, tmp_path: Path) -> None:
        validated = _writeSprintJson(
            tmp_path / "ready.json",
            currentVersion="V0.99.5",
            validatedAt="2026-06-01T00:00:00Z",
            validatedBy="Mike",
            validatesFeatures=["F-001"],
        )

        result = subprocess.run(
            [
                sys.executable,
                str(_SCRIPT_PATH),
                "--chain",
                "V0.99",
                "--paths",
                str(validated),
                "--strict",
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, (
            f"expected exit 0 (READY+strict), got {result.returncode}: {result.stderr}"
        )


# ================================================================================
# 7. chain_validate_manifest_bump.bumpManifestForChain() -- happy path
# ================================================================================


class TestBumpManifestForChain:
    """Bumps lastValidated + validatedBy on matching feature records.

    /chain-validated Phase 3: for each feature in any chain sprint's
    validatesFeatures, mark it validated by the chain merge.
    """

    def test_bumpManifestForChain_matchingFeatures_updatesLastValidated(
        self, tmp_path: Path
    ) -> None:
        """Given: manifest with 3 features (F-001, F-002, F-003) all lastValidated=null.

        When: bumpManifestForChain is called for [F-001, F-003] with chain-merge label.

        Then: F-001 + F-003 lastValidated bumped to merge date + validatedBy carries
            the chain-merge label; F-002 is untouched.
        """
        mod = _loadBump()
        manifestPath = _writeManifest(
            tmp_path / "m.json",
            features=[
                {"id": "F-001", "name": "feat-1", "lastValidated": None, "validatedBy": "synth"},
                {"id": "F-002", "name": "feat-2", "lastValidated": None, "validatedBy": "synth"},
                {"id": "F-003", "name": "feat-3", "lastValidated": None, "validatedBy": "synth"},
            ],
        )

        bumped = mod.bumpManifestForChain(
            manifestPath,
            featureIds=["F-001", "F-003"],
            validationLabel="by chain merge V0.99.5",
            mergeDate="2026-06-01",
        )

        assert sorted(bumped) == ["F-001", "F-003"]

        result = json.loads(manifestPath.read_text(encoding="utf-8"))
        byId = {f["id"]: f for f in result["features"]}
        assert byId["F-001"]["lastValidated"] == "2026-06-01"
        assert byId["F-001"]["validatedBy"] == "by chain merge V0.99.5"
        assert byId["F-003"]["lastValidated"] == "2026-06-01"
        assert byId["F-003"]["validatedBy"] == "by chain merge V0.99.5"
        # Untouched feature
        assert byId["F-002"]["lastValidated"] is None
        assert byId["F-002"]["validatedBy"] == "synth"

    def test_bumpManifestForChain_dryRun_doesNotMutateFile(self, tmp_path: Path) -> None:
        mod = _loadBump()
        manifestPath = _writeManifest(
            tmp_path / "m.json",
            features=[{"id": "F-001", "name": "f", "lastValidated": None, "validatedBy": "synth"}],
        )
        beforeMtime = manifestPath.stat().st_mtime_ns
        beforeText = manifestPath.read_text(encoding="utf-8")

        mod.bumpManifestForChain(
            manifestPath,
            featureIds=["F-001"],
            validationLabel="by chain merge V0.99.5",
            mergeDate="2026-06-01",
            dryRun=True,
        )

        assert manifestPath.read_text(encoding="utf-8") == beforeText
        assert manifestPath.stat().st_mtime_ns == beforeMtime

    def test_bumpManifestForChain_unknownFeatureId_skippedAndReported(
        self, tmp_path: Path
    ) -> None:
        """Unknown IDs are skipped (not in bumped list); known IDs still process."""
        mod = _loadBump()
        manifestPath = _writeManifest(
            tmp_path / "m.json",
            features=[{"id": "F-001", "name": "f", "lastValidated": None, "validatedBy": "synth"}],
        )

        bumped = mod.bumpManifestForChain(
            manifestPath,
            featureIds=["F-001", "F-NONEXIST"],
            validationLabel="by chain merge V0.99.5",
            mergeDate="2026-06-01",
        )

        assert bumped == ["F-001"]
